import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Notification, SystemSetting, User, UserRole
from .security import decode_access_token, decrypt_secret, encrypt_secret
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter()
bearer = HTTPBearer(auto_error=False)

CHANNELS = ("email", "whatsapp")


class NotificationIntegrationWrite(BaseModel):
    email_enabled: bool = False
    email_webhook_url: str | None = Field(default=None, max_length=1000)
    email_webhook_token: str | None = Field(default=None, max_length=2000)
    whatsapp_enabled: bool = False
    whatsapp_webhook_url: str | None = Field(default=None, max_length=1000)
    whatsapp_webhook_token: str | None = Field(default=None, max_length=2000)


def _setting(db: Session, key: str, secret: bool = False) -> str | None:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if not row or not row.value:
        return None
    return decrypt_secret(row.value) if secret and row.encrypted else row.value


def _set_setting(db: Session, key: str, value: str | None, encrypted: bool = False) -> None:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    stored = encrypt_secret(value) if encrypted and value else value
    if row:
        row.value = stored
        row.encrypted = encrypted
    else:
        db.add(SystemSetting(key=key, value=stored, encrypted=encrypted))


def _enabled(db: Session, channel: str) -> bool:
    return (_setting(db, f"notifications.{channel}_enabled") or "").lower() == "true"


def _super_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        user_id = int(decode_access_token(credentials.credentials)["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def integration_status(db: Session) -> dict:
    return {
        "email_enabled": _enabled(db, "email"),
        "email_webhook_url": _setting(db, "notifications.email_webhook_url"),
        "email_webhook_token_configured": bool(_setting(db, "notifications.email_webhook_token", True)),
        "whatsapp_enabled": _enabled(db, "whatsapp"),
        "whatsapp_webhook_url": _setting(db, "notifications.whatsapp_webhook_url"),
        "whatsapp_webhook_token_configured": bool(_setting(db, "notifications.whatsapp_webhook_token", True)),
    }


@router.get("/api/v1/system/integrations/notifications")
def get_notification_integrations(_: User = Depends(_super_admin), db: Session = Depends(get_db)):
    return integration_status(db)


@router.put("/api/v1/system/integrations/notifications")
def update_notification_integrations(payload: NotificationIntegrationWrite, _: User = Depends(_super_admin), db: Session = Depends(get_db)):
    if payload.email_enabled and not payload.email_webhook_url:
        raise HTTPException(status_code=400, detail="Email webhook URL is required when email delivery is enabled")
    if payload.whatsapp_enabled and not payload.whatsapp_webhook_url:
        raise HTTPException(status_code=400, detail="WhatsApp webhook URL is required when WhatsApp delivery is enabled")

    _set_setting(db, "notifications.email_enabled", "true" if payload.email_enabled else "false")
    _set_setting(db, "notifications.email_webhook_url", payload.email_webhook_url)
    _set_setting(db, "notifications.whatsapp_enabled", "true" if payload.whatsapp_enabled else "false")
    _set_setting(db, "notifications.whatsapp_webhook_url", payload.whatsapp_webhook_url)
    if payload.email_webhook_token:
        _set_setting(db, "notifications.email_webhook_token", payload.email_webhook_token, True)
    if payload.whatsapp_webhook_token:
        _set_setting(db, "notifications.whatsapp_webhook_token", payload.whatsapp_webhook_token, True)
    db.commit()
    return integration_status(db)


def _send(channel: str, url: str, token: str | None, notification: Notification, user: User) -> None:
    target = user.email if channel == "email" else user.phone
    if not target:
        raise ValueError(f"Advertiser has no {channel} destination configured")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "channel": channel,
        "recipient": target,
        "notification_id": notification.id,
        "kind": notification.kind,
        "title": notification.title,
        "message": notification.message,
    }
    response = httpx.post(url, json=payload, headers=headers, timeout=float(os.getenv("NOTIFICATION_WEBHOOK_TIMEOUT_SECONDS", "10")))
    response.raise_for_status()


def deliver_pending_notifications(db: Session) -> int:
    max_attempts = max(1, int(os.getenv("NOTIFICATION_MAX_ATTEMPTS", "5")))
    batch_size = max(1, int(os.getenv("NOTIFICATION_BATCH_SIZE", "50")))
    email_enabled = _enabled(db, "email")
    whatsapp_enabled = _enabled(db, "whatsapp")
    if not email_enabled and not whatsapp_enabled:
        return 0

    conditions = []
    if email_enabled:
        conditions.append((Notification.email_sent_at.is_(None)) & (Notification.email_attempts < max_attempts))
    if whatsapp_enabled:
        conditions.append((Notification.whatsapp_sent_at.is_(None)) & (Notification.whatsapp_attempts < max_attempts))
    rows = list(db.scalars(select(Notification).where(or_(*conditions)).order_by(Notification.created_at).limit(batch_size)))
    delivered = 0

    for item in rows:
        user = db.get(User, item.user_id)
        if not user or not user.is_active:
            continue
        for channel, enabled in (("email", email_enabled), ("whatsapp", whatsapp_enabled)):
            if not enabled:
                continue
            sent_attr = f"{channel}_sent_at"
            attempts_attr = f"{channel}_attempts"
            error_attr = f"{channel}_last_error"
            if getattr(item, sent_attr) is not None or getattr(item, attempts_attr) >= max_attempts:
                continue
            url = _setting(db, f"notifications.{channel}_webhook_url")
            token = _setting(db, f"notifications.{channel}_webhook_token", True)
            if not url:
                continue
            setattr(item, attempts_attr, getattr(item, attempts_attr) + 1)
            try:
                _send(channel, url, token, item, user)
                setattr(item, sent_attr, datetime.now(timezone.utc))
                setattr(item, error_attr, None)
                delivered += 1
            except Exception as exc:
                setattr(item, error_attr, str(exc)[:2000])
        db.commit()
    return delivered
