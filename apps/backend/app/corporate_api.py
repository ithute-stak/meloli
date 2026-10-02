import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AdvertisingPackage, AuditLog, Campaign, CampaignMedia, CampaignStatus, CorporateAccount, CorporateApiClient, Payment, PaymentStatus, User, UserRole
from .security import decrypt_secret, encrypt_secret, validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class CorporateApiClientCreate(BaseModel):
    user_id: int
    name: str = Field(min_length=2, max_length=180)
    webhook_url: str | None = Field(default=None, max_length=1000)


class CorporateMedia(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    content_type: str = Field(min_length=3, max_length=120)


class CorporateApiClientState(BaseModel):
    active: bool


class CorporateCampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    caption: str = Field(min_length=3, max_length=5000)
    package_code: str = Field(min_length=2, max_length=50)
    preferred_publish_at: datetime | None = None
    destination_url: str | None = Field(default=None, max_length=1000)
    media_items: list[CorporateMedia] = Field(default_factory=list, max_length=10)


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


def audit(db: Session, actor: User | None, action: str, entity_type: str, entity_id: int | str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id if actor else None, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, detail=detail))


def _client_from_key(db: Session, raw_key: str | None) -> tuple[CorporateApiClient, CorporateAccount, User]:
    if not raw_key:
        raise HTTPException(status_code=401, detail="X-API-Key is required")
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    client = db.scalar(select(CorporateApiClient).where(CorporateApiClient.key_hash == digest, CorporateApiClient.active.is_(True)))
    if not client:
        raise HTTPException(status_code=401, detail="Invalid corporate API key")
    account = db.get(CorporateAccount, client.corporate_account_id)
    user = db.get(User, account.user_id) if account else None
    if not account or not user or not account.active or not user.is_active:
        raise HTTPException(status_code=403, detail="Corporate API account is inactive")
    client.last_used_at = datetime.now(timezone.utc)
    return client, account, user


@router.post("/api/v1/admin/corporate-api/clients", status_code=201)
def create_api_client(payload: CorporateApiClientCreate, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    account = db.scalar(select(CorporateAccount).where(CorporateAccount.user_id == payload.user_id, CorporateAccount.active.is_(True)))
    if not account:
        raise HTTPException(status_code=404, detail="Active corporate account not found")
    raw_key = "mel_" + secrets.token_urlsafe(36)
    webhook_secret = secrets.token_urlsafe(36)
    row = CorporateApiClient(
        corporate_account_id=account.id,
        name=payload.name.strip(),
        key_prefix=raw_key[:12],
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        webhook_url=payload.webhook_url.strip() if payload.webhook_url else None,
        webhook_secret=encrypt_secret(webhook_secret),
        active=True,
        created_by_user_id=admin.id,
    )
    db.add(row); db.flush()
    audit(db, admin, "corporate_api.client_created", "corporate_api_client", row.id, f"user {payload.user_id}")
    db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "user_id": payload.user_id,
        "api_key": raw_key,
        "key_prefix": row.key_prefix,
        "webhook_url": row.webhook_url,
        "webhook_secret": webhook_secret,
        "note": "Store the API key and webhook secret now; they are not returned again.",
    }


@router.get("/api/v1/admin/corporate-api/clients")
def list_api_clients(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(CorporateApiClient).order_by(CorporateApiClient.created_at.desc())))
    result = []
    for row in rows:
        account = db.get(CorporateAccount, row.corporate_account_id)
        user = db.get(User, account.user_id) if account else None
        result.append({
            "id": row.id,
            "name": row.name,
            "user_id": account.user_id if account else None,
            "advertiser": (user.business_name or user.full_name) if user else None,
            "key_prefix": row.key_prefix,
            "webhook_url": row.webhook_url,
            "active": row.active,
            "last_used_at": row.last_used_at,
            "created_at": row.created_at,
        })
    return result


@router.patch("/api/v1/admin/corporate-api/clients/{client_id}/state")
def set_api_client_state(client_id: int, payload: CorporateApiClientState, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = db.get(CorporateApiClient, client_id)
    if not row:
        raise HTTPException(status_code=404, detail="Corporate API client not found")
    row.active = payload.active
    audit(db, admin, "corporate_api.client_enabled" if payload.active else "corporate_api.client_disabled", "corporate_api_client", row.id, row.name)
    db.commit()
    return {"id": row.id, "active": row.active}


@router.post("/api/v1/corporate-api/campaigns", status_code=201)
def api_create_campaign(payload: CorporateCampaignCreate, x_api_key: str | None = Header(default=None, alias="X-API-Key"), db: Session = Depends(get_db)):
    client, account, user = _client_from_key(db, x_api_key)
    package = db.scalar(select(AdvertisingPackage).where(AdvertisingPackage.code == payload.package_code.upper(), AdvertisingPackage.active.is_(True)))
    if not package:
        raise HTTPException(status_code=400, detail="Advertising package is unavailable")
    items = list(payload.media_items or [])
    if len(items) > int(package.max_media_items or 10):
        raise HTTPException(status_code=400, detail=f"{package.name} allows at most {package.max_media_items} media item(s)")
    if len(items) > 1 and (not package.allow_carousel or any(not item.content_type.lower().startswith("image/") for item in items)):
        raise HTTPException(status_code=400, detail="This package/media combination cannot be submitted as a carousel")
    if any(item.content_type.lower().startswith("video/") for item in items) and not package.allow_video:
        raise HTTPException(status_code=400, detail=f"{package.name} does not allow video adverts")

    amount = Decimal(str(package.price))
    available = Decimal(str(account.credit_limit or 0)) - Decimal(str(account.credit_used or 0))
    if amount > available:
        raise HTTPException(status_code=402, detail="Corporate credit limit is insufficient for this campaign")

    campaign = Campaign(
        advertiser_id=user.id,
        package_id=package.id,
        title=payload.title.strip(),
        caption=payload.caption.strip(),
        media_url=items[0].url if items else None,
        destination_url=payload.destination_url,
        preferred_publish_at=payload.preferred_publish_at,
        status=CampaignStatus.SUBMITTED,
    )
    db.add(campaign); db.flush()
    for position, item in enumerate(items):
        db.add(CampaignMedia(campaign_id=campaign.id, url=item.url, content_type=item.content_type.lower(), position=position))
    payment = Payment(
        campaign_id=campaign.id,
        amount=amount,
        currency=package.currency,
        method="corporate_credit",
        reference=f"API-{client.id}-{campaign.id}",
        status=PaymentStatus.PAID,
        paid_at=datetime.now(timezone.utc),
    )
    account.credit_used = Decimal(str(account.credit_used or 0)) + amount
    db.add(payment)
    audit(db, None, "corporate_api.campaign_created", "campaign", campaign.id, f"client {client.id}")
    db.commit(); db.refresh(campaign)
    emit_corporate_webhook(db, campaign, "campaign.submitted")
    return {
        "id": campaign.id,
        "status": campaign.status,
        "proof_status": campaign.proof_status,
        "amount": float(payment.amount),
        "currency": payment.currency,
        "credit_remaining": float(Decimal(str(account.credit_limit or 0)) - Decimal(str(account.credit_used or 0))),
    }


@router.get("/api/v1/corporate-api/campaigns")
def api_list_campaigns(x_api_key: str | None = Header(default=None, alias="X-API-Key"), db: Session = Depends(get_db)):
    _, _, user = _client_from_key(db, x_api_key)
    rows = list(db.scalars(select(Campaign).where(Campaign.advertiser_id == user.id).order_by(Campaign.created_at.desc()).limit(200)))
    db.commit()
    return [{
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "proof_status": row.proof_status,
        "scheduled_publish_at": row.scheduled_publish_at,
        "facebook_post_url": row.facebook_post_url,
        "cancelled_at": row.cancelled_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    } for row in rows]


def emit_corporate_webhook(db: Session, campaign: Campaign, event: str) -> None:
    account = db.scalar(select(CorporateAccount).where(CorporateAccount.user_id == campaign.advertiser_id))
    if not account:
        return
    clients = list(db.scalars(
        select(CorporateApiClient)
        .where(
            CorporateApiClient.corporate_account_id == account.id,
            CorporateApiClient.active.is_(True),
            CorporateApiClient.webhook_url.is_not(None),
        )
    ))
    payload = {
        "event": event,
        "campaign": {
            "id": campaign.id,
            "title": campaign.title,
            "status": campaign.status.value if hasattr(campaign.status, "value") else str(campaign.status),
            "proof_status": campaign.proof_status,
            "scheduled_publish_at": campaign.scheduled_publish_at.isoformat() if campaign.scheduled_publish_at else None,
            "facebook_post_url": campaign.facebook_post_url,
            "cancelled_at": campaign.cancelled_at.isoformat() if campaign.cancelled_at else None,
            "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
        },
    }
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    for client in clients:
        try:
            secret = decrypt_secret(client.webhook_secret) if client.webhook_secret else ""
            signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            httpx.post(
                client.webhook_url,
                content=body,
                headers={"Content-Type": "application/json", "X-Meloli-Signature": "sha256=" + signature},
                timeout=10.0,
            )
        except Exception:
            # Corporate webhooks are best-effort and must never block Meloli operations.
            pass
