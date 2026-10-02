import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Campaign, MetaWebhookEvent, Tenant
from .realtime import emit_realtime_event
from .tenancy import tenant_setting

router = APIRouter()


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
            db.rollback()
            row = db.get(MetaWebhookEvent, row.id)
            if row:
                row.attempts += 1 if row.attempts == 0 else 0
                row.status = "failed"
                row.last_error = str(exc)[:2000]
                failed += 1
                db.commit()

    return {"processed": processed, "failed": failed, "competition_syncs": competitions_synced}
