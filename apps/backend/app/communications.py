import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Notification, NotificationDelivery, SystemSetting, User, UserRole
from .security import decode_access_token, decrypt_secret, encrypt_secret

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class CommunicationsUpdate(BaseModel):
    email_enabled: bool = False
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = None
    from_email: EmailStr | None = None
    smtp_use_tls: bool = True
    webhook_enabled: bool = False
    webhook_url: str | None = Field(default=None, max_length=1000)
    webhook_bearer_token: SecretStr | None = None


def _setting_row(db: Session, key: str) -> SystemSetting | None:
    return db.scalar(select(SystemSetting).where(SystemSetting.key == key))


def setting(db: Session, key: str) -> str | None:
    row = _setting_row(db, key)
    if not row or row.value is None:
        return None
    return decrypt_secret(row.value) if row.encrypted else row.value


def bool_setting(db: Session, key: str) -> bool:
    return (setting(db, key) or "").lower() in {"1", "true", "yes", "on"}


def set_setting(db: Session, key: str, value: str | None, encrypted: bool = False) -> None:
    row = _setting_row(db, key)
    stored = encrypt_secret(value) if encrypted and value is not None else value
    if row:
        row.value = stored
        row.encrypted = encrypted
    else:
        db.add(SystemSetting(key=key, value=stored, encrypted=encrypted))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = int(decode_access_token(credentials.credentials)["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")
    return user


def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def enqueue_notification(db: Session, user_id: int, kind: str, title: str, message: str) -> Notification:
    notification = Notification(user_id=user_id, kind=kind, title=title, message=message)
    db.add(notification)
    db.flush()
    if bool_setting(db, "notifications.email_enabled"):
        db.add(NotificationDelivery(notification_id=notification.id, channel="email"))
    if bool_setting(db, "notifications.webhook_enabled"):
        db.add(NotificationDelivery(notification_id=notification.id, channel="webhook"))
    return notification


def _send_email(db: Session, notification: Notification, user: User) -> None:
    host = setting(db, "notifications.smtp_host")
    from_email = setting(db, "notifications.from_email")
    if not host or not from_email or not user.email:
        raise RuntimeError("SMTP host, from address and recipient email are required")
    port = int(setting(db, "notifications.smtp_port") or "587")
    username = setting(db, "notifications.smtp_username")
    password = setting(db, "notifications.smtp_password")
    use_tls = bool_setting(db, "notifications.smtp_use_tls")
    msg = EmailMessage()
    msg["Subject"] = notification.title
    msg["From"] = from_email
    msg["To"] = user.email
    msg.set_content(notification.message + "\n\nMeloli Airwaves Advertising Portal")
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password or "")
        smtp.send_message(msg)


def _send_webhook(db: Session, notification: Notification, user: User) -> None:
    url = setting(db, "notifications.webhook_url")
    if not url:
        raise RuntimeError("Webhook URL is not configured")
    token = setting(db, "notifications.webhook_bearer_token")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = {
        "event": "meloli.notification",
        "notification": {
            "id": notification.id,
            "kind": notification.kind,
            "title": notification.title,
            "message": notification.message,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        },
        "recipient": {"id": user.id, "email": user.email, "phone": user.phone, "name": user.full_name},
    }
    response = httpx.post(url, json=payload, headers=headers, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError("Webhook returned HTTP " + str(response.status_code))


def deliver_pending(db: Session, limit: int = 30) -> dict[str, int]:
    rows = list(db.scalars(
        select(NotificationDelivery)
        .where(NotificationDelivery.status.in_(["pending", "failed"]), NotificationDelivery.attempts < 5)
        .order_by(NotificationDelivery.created_at)
        .limit(limit)
    ))
    sent = failed = 0
    for delivery in rows:
        notification = db.get(Notification, delivery.notification_id)
        user = db.get(User, notification.user_id) if notification else None
        delivery.attempts += 1
        try:
            if not notification or not user:
                raise RuntimeError("Notification recipient no longer exists")
            if delivery.channel == "email":
                _send_email(db, notification, user)
            elif delivery.channel == "webhook":
                _send_webhook(db, notification, user)
            else:
                raise RuntimeError("Unsupported notification channel")
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
            delivery.last_error = None
            sent += 1
        except Exception as exc:
            delivery.status = "failed"
            delivery.last_error = str(exc)[:2000]
            failed += 1
        db.commit()
    return {"sent": sent, "failed": failed}


@router.get("/api/v1/system/communications")
def communications_status(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    return {
        "email_enabled": bool_setting(db, "notifications.email_enabled"),
        "smtp_host": setting(db, "notifications.smtp_host"),
        "smtp_port": int(setting(db, "notifications.smtp_port") or "587"),
        "smtp_username": setting(db, "notifications.smtp_username"),
        "smtp_password_configured": bool(setting(db, "notifications.smtp_password")),
        "from_email": setting(db, "notifications.from_email"),
        "smtp_use_tls": bool_setting(db, "notifications.smtp_use_tls"),
        "webhook_enabled": bool_setting(db, "notifications.webhook_enabled"),
        "webhook_url": setting(db, "notifications.webhook_url"),
        "webhook_bearer_token_configured": bool(setting(db, "notifications.webhook_bearer_token")),
    }


@router.put("/api/v1/system/communications")
def update_communications(payload: CommunicationsUpdate, _: User = Depends(super_admin), db: Session = Depends(get_db)):
    set_setting(db, "notifications.email_enabled", str(payload.email_enabled).lower())
    set_setting(db, "notifications.smtp_host", payload.smtp_host)
    set_setting(db, "notifications.smtp_port", str(payload.smtp_port))
    set_setting(db, "notifications.smtp_username", payload.smtp_username)
    if payload.smtp_password is not None:
        set_setting(db, "notifications.smtp_password", payload.smtp_password.get_secret_value(), encrypted=True)
    set_setting(db, "notifications.from_email", str(payload.from_email) if payload.from_email else None)
    set_setting(db, "notifications.smtp_use_tls", str(payload.smtp_use_tls).lower())
    set_setting(db, "notifications.webhook_enabled", str(payload.webhook_enabled).lower())
    set_setting(db, "notifications.webhook_url", payload.webhook_url)
    if payload.webhook_bearer_token is not None:
        set_setting(db, "notifications.webhook_bearer_token", payload.webhook_bearer_token.get_secret_value(), encrypted=True)
    db.commit()
    return communications_status(_, db)


@router.get("/api/v1/admin/notification-deliveries")
def delivery_status(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc()).limit(100)))
    return [{"id":r.id,"notification_id":r.notification_id,"channel":r.channel,"status":r.status,"attempts":r.attempts,"last_error":r.last_error,"sent_at":r.sent_at,"created_at":r.created_at} for r in rows]
