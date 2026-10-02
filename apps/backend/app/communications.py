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
from .models import AuditLog, Notification, NotificationDelivery, SystemSetting, User, UserRole
from .security import validate_token_user, decrypt_secret, encrypt_secret

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
    whatsapp_enabled: bool = False
    whatsapp_phone_number_id: str | None = Field(default=None, max_length=100)
    whatsapp_access_token: SecretStr | None = None
    whatsapp_graph_version: str = Field(default="v24.0", max_length=32)
    whatsapp_template_name: str | None = Field(default=None, max_length=160)
    whatsapp_template_language: str = Field(default="en", max_length=20)


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
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


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
    if bool_setting(db, "notifications.whatsapp_enabled"):
        db.add(NotificationDelivery(notification_id=notification.id, channel="whatsapp"))
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


def send_direct_email(db: Session, recipient: str, subject: str, body: str, attachment: bytes | None = None, attachment_name: str | None = None) -> None:
    host = setting(db, "notifications.smtp_host")
    from_email = setting(db, "notifications.from_email")
    if not host or not from_email:
        raise RuntimeError("SMTP host and from address are required")
    port = int(setting(db, "notifications.smtp_port") or "587")
    username = setting(db, "notifications.smtp_username")
    password = setting(db, "notifications.smtp_password")
    use_tls = bool_setting(db, "notifications.smtp_use_tls")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = recipient
    msg.set_content(body)
    if attachment is not None:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=attachment_name or "document.pdf")
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


def _normalize_phone(value: str | None) -> str:
    if not value:
        raise RuntimeError("Recipient phone number is missing")
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        raise RuntimeError("Recipient phone number is invalid")
    if digits.startswith("0"):
        raise RuntimeError("Recipient phone number must include country code")
    return digits


def _send_whatsapp(db: Session, notification: Notification, user: User) -> None:
    phone_number_id = setting(db, "notifications.whatsapp_phone_number_id")
    access_token = setting(db, "notifications.whatsapp_access_token")
    version = setting(db, "notifications.whatsapp_graph_version") or "v24.0"
    template_name = setting(db, "notifications.whatsapp_template_name")
    language = setting(db, "notifications.whatsapp_template_language") or "en"
    if not phone_number_id or not access_token or not template_name:
        raise RuntimeError("WhatsApp Phone Number ID, access token and approved template name are required")
    to = _normalize_phone(user.phone)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": notification.title[:1024]},
                    {"type": "text", "text": notification.message[:1024]},
                ],
            }],
        },
    }
    response = httpx.post(
        f"https://graph.facebook.com/{version}/{phone_number_id}/messages",
        json=payload,
        headers={"Authorization": "Bearer " + access_token, "Content-Type": "application/json"},
        timeout=20,
    )
    if response.status_code >= 400:
        detail = response.text[:1000]
        raise RuntimeError(f"WhatsApp Cloud API returned HTTP {response.status_code}: {detail}")


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
            elif delivery.channel == "whatsapp":
                _send_whatsapp(db, notification, user)
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
        "whatsapp_enabled": bool_setting(db, "notifications.whatsapp_enabled"),
        "whatsapp_phone_number_id": setting(db, "notifications.whatsapp_phone_number_id"),
        "whatsapp_access_token_configured": bool(setting(db, "notifications.whatsapp_access_token")),
        "whatsapp_graph_version": setting(db, "notifications.whatsapp_graph_version") or "v24.0",
        "whatsapp_template_name": setting(db, "notifications.whatsapp_template_name"),
        "whatsapp_template_language": setting(db, "notifications.whatsapp_template_language") or "en",
    }


@router.put("/api/v1/system/communications")
def update_communications(payload: CommunicationsUpdate, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    existing_smtp_password = setting(db, "notifications.smtp_password")
    existing_whatsapp_token = setting(db, "notifications.whatsapp_access_token")
    if payload.email_enabled and (not payload.smtp_host or not payload.from_email):
        raise HTTPException(status_code=400, detail="SMTP host and from email are required before email delivery can be enabled")
    if payload.smtp_username and not (payload.smtp_password or existing_smtp_password):
        raise HTTPException(status_code=400, detail="SMTP password is required when an SMTP username is configured")
    if payload.webhook_enabled and not payload.webhook_url:
        raise HTTPException(status_code=400, detail="Webhook URL is required before webhook delivery can be enabled")
    if payload.whatsapp_enabled:
        if not payload.whatsapp_phone_number_id or not payload.whatsapp_template_name:
            raise HTTPException(status_code=400, detail="WhatsApp Phone Number ID and approved template name are required")
        if not (payload.whatsapp_access_token or existing_whatsapp_token):
            raise HTTPException(status_code=400, detail="WhatsApp access token is required before WhatsApp delivery can be enabled")
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
    set_setting(db, "notifications.whatsapp_enabled", str(payload.whatsapp_enabled).lower())
    set_setting(db, "notifications.whatsapp_phone_number_id", payload.whatsapp_phone_number_id)
    set_setting(db, "notifications.whatsapp_graph_version", payload.whatsapp_graph_version)
    set_setting(db, "notifications.whatsapp_template_name", payload.whatsapp_template_name)
    set_setting(db, "notifications.whatsapp_template_language", payload.whatsapp_template_language)
    if payload.whatsapp_access_token is not None:
        set_setting(db, "notifications.whatsapp_access_token", payload.whatsapp_access_token.get_secret_value(), encrypted=True)
    db.add(AuditLog(actor_user_id=admin.id, action="communications.configuration_updated", entity_type="system_setting", detail="Email/webhook/WhatsApp delivery configuration updated"))
    db.commit()
    return communications_status(admin, db)


class DeliveryTest(BaseModel):
    recipient: str = Field(min_length=3, max_length=255)


@router.post("/api/v1/system/communications/test-email")
def test_email(payload: DeliveryTest, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    try:
        send_direct_email(
            db,
            payload.recipient,
            "Meloli notification delivery test",
            "This is a test email from the Meloli Airwaves Advertising Portal. SMTP delivery is working.",
        )
        db.add(AuditLog(actor_user_id=admin.id, action="communications.email_test_sent", entity_type="notification_delivery", detail=payload.recipient))
        db.commit()
        return {"ok": True, "recipient": payload.recipient}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/v1/system/communications/test-whatsapp")
def test_whatsapp(payload: DeliveryTest, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    notification = Notification(
        user_id=admin.id,
        kind="delivery_test",
        title="Meloli delivery test",
        message="WhatsApp Cloud API delivery is working for the Meloli Airwaves Advertising Portal.",
    )
    db.add(notification)
    db.flush()
    original_phone = admin.phone
    admin.phone = payload.recipient
    try:
        _send_whatsapp(db, notification, admin)
        db.rollback()
        db.add(AuditLog(actor_user_id=admin.id, action="communications.whatsapp_test_sent", entity_type="notification_delivery", detail=payload.recipient))
        db.commit()
        return {"ok": True, "recipient": payload.recipient}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        admin.phone = original_phone


@router.get("/api/v1/admin/notification-deliveries")
def delivery_status(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc()).limit(100)))
    return [{"id":r.id,"notification_id":r.notification_id,"channel":r.channel,"status":r.status,"attempts":r.attempts,"last_error":r.last_error,"sent_at":r.sent_at,"created_at":r.created_at} for r in rows]



@router.post("/api/v1/admin/notification-deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: int, _: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = db.get(NotificationDelivery, delivery_id)
    if not row:
        raise HTTPException(status_code=404, detail="Notification delivery not found")
    row.status = "pending"
    row.attempts = 0
    row.last_error = None
    row.sent_at = None
    db.commit()
    return {"id": row.id, "status": row.status, "attempts": row.attempts}


@router.post("/api/v1/admin/notification-deliveries/retry-failed")
def retry_failed_deliveries(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(NotificationDelivery).where(NotificationDelivery.status == "failed")))
    for row in rows:
        row.status = "pending"
        row.attempts = 0
        row.last_error = None
        row.sent_at = None
    db.commit()
    return {"reset": len(rows)}
