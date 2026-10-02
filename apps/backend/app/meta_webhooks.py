import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Campaign, MetaWebhookEvent, Tenant, User, UserRole
from .realtime import emit_realtime_event
from .tenancy import tenant_setting
from .security import validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def _verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    supplied = signature.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, supplied)


def _tenant_for_page(db: Session, page_id: str | None) -> Tenant | None:
    if not page_id:
        return None
    tenant = db.scalar(select(Tenant).where(Tenant.facebook_page_id == page_id))
    if tenant:
        return tenant
    # fall back to the tenant Meta Page setting for portals not yet mirrored
    for candidate in db.scalars(select(Tenant).where(Tenant.active.is_(True))):
        if tenant_setting(db, candidate.id, "meta.page_id") == page_id:
            return candidate
    return None


@router.get("/api/v1/meta/webhook")
def verify_meta_webhook(request: Request, db: Session = Depends(get_db)):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode != "subscribe" or not token or challenge is None:
        raise HTTPException(status_code=400, detail="Invalid Meta webhook verification request")
    for tenant in db.scalars(select(Tenant).where(Tenant.active.is_(True))):
        configured = tenant_setting(db, tenant.id, "meta.webhook_verify_token")
        if configured and hmac.compare_digest(configured, token):
            return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Webhook verification token is invalid")


@router.post("/api/v1/meta/webhook", status_code=200)
async def receive_meta_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Meta webhook JSON") from exc

    entries = payload.get("entry") or []
    if not isinstance(entries, list) or not entries:
        return {"received": True, "accepted": 0}

    tenants: dict[int, Tenant] = {}
    for entry in entries:
        tenant = _tenant_for_page(db, str(entry.get("id") or ""))
        if tenant:
            tenants[tenant.id] = tenant
    if not tenants:
        raise HTTPException(status_code=404, detail="Webhook Page is not registered")

    signature = request.headers.get("X-Hub-Signature-256")
    if not any(_verify_signature(tenant_setting(db, tenant.id, "meta.app_secret") or "", body, signature) for tenant in tenants.values()):
        raise HTTPException(status_code=401, detail="Meta webhook signature is invalid")

    accepted = 0
    for entry in entries:
        page_id = str(entry.get("id") or "") or None
        tenant = _tenant_for_page(db, page_id)
        if not tenant:
            continue
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256((str(tenant.id) + ":" + canonical).encode("utf-8")).hexdigest()
        exists = db.scalar(select(MetaWebhookEvent.id).where(MetaWebhookEvent.payload_sha256 == digest))
        if exists:
            continue
        row = MetaWebhookEvent(
            tenant_id=tenant.id,
            page_id=page_id,
            object_type=str(payload.get("object") or "page"),
            payload_sha256=digest,
            payload_json=canonical,
            status="pending",
        )
        db.add(row)
        db.flush()
        db.add(AuditLog(actor_user_id=None, action="meta.webhook_received", entity_type="meta_webhook_event", entity_id=str(row.id), detail=page_id))
        emit_realtime_event(
            db,
            "meta.webhook_received",
            tenant_id=tenant.id,
            audience="tenant_staff",
            entity_type="meta_webhook_event",
            entity_id=row.id,
            payload={"page_id": page_id, "event_id": row.id},
        )
        accepted += 1
    db.commit()
    return {"received": True, "accepted": accepted}


def _post_ids_from_entry(entry: dict) -> set[str]:
    result: set[str] = set()
    for change in entry.get("changes") or []:
        value = change.get("value") or {}
        for key in ("post_id", "parent_id", "comment_id"):
            raw = value.get(key)
            if raw:
                result.add(str(raw))
        post = value.get("post")
        if isinstance(post, dict) and post.get("id"):
            result.add(str(post["id"]))
    return result


def process_meta_webhook_events(db: Session, limit: int = 50) -> dict[str, int]:
    from .competition import sync_competition_campaign

    rows = list(db.scalars(
        select(MetaWebhookEvent)
        .where(MetaWebhookEvent.status.in_(["pending", "failed"]), MetaWebhookEvent.attempts < 5)
        .order_by(MetaWebhookEvent.received_at)
        .limit(limit)
    ))
    processed = failed = competitions_synced = 0
    for row in rows:
        row.attempts += 1
        try:
            entry = json.loads(row.payload_json)
            post_ids = _post_ids_from_entry(entry)
            campaigns = []
            if row.tenant_id:
                query = select(Campaign).where(Campaign.tenant_id == row.tenant_id, Campaign.facebook_post_id.is_not(None))
                for campaign in db.scalars(query):
                    if not post_ids or campaign.facebook_post_id in post_ids or any(pid.endswith("_" + campaign.facebook_post_id) for pid in post_ids):
                        campaigns.append(campaign)

            for campaign in campaigns:
                emit_realtime_event(
                    db,
                    "meta.campaign_activity",
                    tenant_id=campaign.tenant_id,
                    audience="tenant_staff",
                    entity_type="campaign",
                    entity_id=campaign.id,
                    payload={"campaign_id": campaign.id, "webhook_event_id": row.id},
                )
                if campaign.engagement_mode == "competition_one_comment":
                    if sync_competition_campaign(db, campaign):
                        competitions_synced += 1

            row.status = "processed"
            row.processed_at = datetime.now(timezone.utc)
            row.last_error = None
            processed += 1
            db.commit()
        except Exception as exc:
            event_id = row.id
            attempted = int(row.attempts or 0)
            db.rollback()
            row = db.get(MetaWebhookEvent, event_id)
            if row:
                row.attempts = max(int(row.attempts or 0), attempted)
                row.status = "dead_letter" if row.attempts >= 5 else "failed"
                row.last_error = str(exc)[:2000]
                failed += 1
                if row.status == "dead_letter":
                    emit_realtime_event(
                        db,
                        "meta.webhook_dead_letter",
                        tenant_id=row.tenant_id,
                        audience="tenant_staff" if row.tenant_id else "platform_admins",
                        entity_type="meta_webhook_event",
                        entity_id=row.id,
                        payload={"event_id": row.id, "page_id": row.page_id, "attempts": row.attempts, "error": row.last_error},
                    )
                    emit_realtime_event(
                        db,
                        "meta.webhook_dead_letter",
                        tenant_id=row.tenant_id,
                        audience="platform_admins",
                        entity_type="meta_webhook_event",
                        entity_id=row.id,
                        payload={"event_id": row.id, "tenant_id": row.tenant_id, "page_id": row.page_id, "attempts": row.attempts, "error": row.last_error},
                    )
                    db.add(AuditLog(actor_user_id=None, action="meta.webhook_dead_letter", entity_type="meta_webhook_event", entity_id=str(row.id), detail=row.last_error))
                db.commit()

    return {"processed": processed, "failed": failed, "competition_syncs": competitions_synced}


@router.get("/api/v1/admin/meta/webhook-events")
def list_meta_webhook_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin:
        raise HTTPException(status_code=403, detail="Portal staff access required")
    query = select(MetaWebhookEvent).order_by(MetaWebhookEvent.received_at.desc()).limit(200)
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id:
            raise HTTPException(status_code=403, detail="Staff account is not attached to a tenant")
        query = query.where(MetaWebhookEvent.tenant_id == user.tenant_id)
    rows = list(db.scalars(query))
    return [{
        "id": row.id,
        "tenant_id": row.tenant_id,
        "page_id": row.page_id,
        "object_type": row.object_type,
        "status": row.status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "received_at": row.received_at,
        "processed_at": row.processed_at,
    } for row in rows]


@router.post("/api/v1/admin/meta/webhook-events/{event_id}/retry")
def retry_meta_webhook_event(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(MetaWebhookEvent, event_id)
    if not row:
        raise HTTPException(status_code=404, detail="Webhook event not found")
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id or row.tenant_id != user.tenant_id or not user.is_tenant_admin:
            raise HTTPException(status_code=403, detail="Tenant administrator access required")
    row.status = "pending"
    row.attempts = 0
    row.last_error = None
    row.processed_at = None
    db.add(AuditLog(actor_user_id=user.id, action="meta.webhook_retry_requested", entity_type="meta_webhook_event", entity_id=str(row.id)))
    db.commit()
    return {"id": row.id, "status": row.status, "attempts": row.attempts}
