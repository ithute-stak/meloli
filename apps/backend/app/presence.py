from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Campaign, CampaignReviewPresence, User, UserRole
from .realtime import emit_realtime_event
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


def _campaign_for_staff(db: Session, campaign_id: int, user: User) -> Campaign:
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin:
        raise HTTPException(status_code=403, detail="Campaign review staff access required")
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id or campaign.tenant_id != user.tenant_id:
            raise HTTPException(status_code=403, detail="Campaign belongs to another tenant")
    return campaign


def _prune(db: Session, campaign_id: int | None = None) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
    query = delete(CampaignReviewPresence).where(CampaignReviewPresence.last_seen_at < cutoff)
    if campaign_id is not None:
        query = query.where(CampaignReviewPresence.campaign_id == campaign_id)
    result = db.execute(query)
    return int(result.rowcount or 0)


@router.post("/api/v1/campaigns/{campaign_id}/presence/heartbeat")
def presence_heartbeat(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = _campaign_for_staff(db, campaign_id, user)
    _prune(db, campaign_id)
    row = db.scalar(select(CampaignReviewPresence).where(
        CampaignReviewPresence.campaign_id == campaign.id,
        CampaignReviewPresence.user_id == user.id,
    ))
    now = datetime.now(timezone.utc)
    if row is None:
        row = CampaignReviewPresence(
            campaign_id=campaign.id,
            user_id=user.id,
            tenant_id=campaign.tenant_id,
            last_seen_at=now,
        )
        db.add(row)
    else:
        row.last_seen_at = now
    emit_realtime_event(
        db,
        "campaign.presence_changed",
        tenant_id=campaign.tenant_id,
        audience="tenant_staff",
        entity_type="campaign",
        entity_id=campaign.id,
        payload={"campaign_id": campaign.id, "user_id": user.id, "active": True, "full_name": user.full_name},
    )
    db.commit()
    return {"campaign_id": campaign.id, "user_id": user.id, "last_seen_at": row.last_seen_at}


@router.delete("/api/v1/campaigns/{campaign_id}/presence")
def leave_presence(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = _campaign_for_staff(db, campaign_id, user)
    row = db.scalar(select(CampaignReviewPresence).where(
        CampaignReviewPresence.campaign_id == campaign.id,
        CampaignReviewPresence.user_id == user.id,
    ))
    if row:
        db.delete(row)
        emit_realtime_event(
            db,
            "campaign.presence_changed",
            tenant_id=campaign.tenant_id,
            audience="tenant_staff",
            entity_type="campaign",
            entity_id=campaign.id,
            payload={"campaign_id": campaign.id, "user_id": user.id, "active": False, "full_name": user.full_name},
        )
        db.commit()
    return {"ok": True}


@router.get("/api/v1/campaigns/{campaign_id}/presence")
def campaign_presence(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = _campaign_for_staff(db, campaign_id, user)
    _prune(db, campaign_id)
    db.commit()
    rows = list(db.scalars(
        select(CampaignReviewPresence)
        .where(CampaignReviewPresence.campaign_id == campaign.id)
        .order_by(CampaignReviewPresence.last_seen_at.desc())
    ))
    result = []
    for row in rows:
        member = db.get(User, row.user_id)
        if not member or not member.is_active:
            continue
        result.append({
            "user_id": member.id,
            "full_name": member.full_name,
            "role": member.role.value,
            "is_tenant_admin": member.is_tenant_admin,
            "last_seen_at": row.last_seen_at,
        })
    return result


def cleanup_review_presence(db: Session) -> dict[str, int]:
    deleted = _prune(db)
    if deleted:
        db.commit()
    return {"deleted": deleted}
