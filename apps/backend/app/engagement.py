from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Campaign, CampaignPerformanceSnapshot, CampaignStatus, SupportTicket, TicketStatus, User, UserRole
from .security import validate_token_user, decrypt_secret, encrypt_secret, hash_password, verify_password
import pyotp

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    business_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class TwoFactorEnable(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class TwoFactorDisable(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=8)


class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=180)
    message: str = Field(min_length=5, max_length=5000)
    campaign_id: int | None = None


class TicketUpdate(BaseModel):
    status: TicketStatus
    staff_reply: str | None = Field(default=None, max_length=5000)


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    campaign_id: int | None
    subject: str
    message: str
    status: TicketStatus
    staff_reply: str | None
    created_at: datetime
    updated_at: datetime


class PerformanceHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: int
    impressions: int | None
    reach: int | None
    engaged_users: int | None
    clicks: int | None
    reactions: int | None
    comments: int | None
    shares: int | None
    video_views: int | None
    captured_at: datetime


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def staff_user(user: User = Depends(current_user)) -> User:
    if user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Meloli staff access required")
    return user


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: int | str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, detail=detail))


@router.patch("/api/v1/profile")
def update_profile(payload: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.full_name = payload.full_name.strip()
    user.business_name = payload.business_name.strip() if payload.business_name else None
    user.phone = payload.phone.strip() if payload.phone else None
    audit(db, user, "profile.updated", "user", user.id)
    db.commit()
    return {"id": user.id, "full_name": user.full_name, "business_name": user.business_name, "email": user.email, "phone": user.phone, "role": user.role}


@router.post("/api/v1/profile/password")
def change_password(payload: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different")
    user.password_hash = hash_password(payload.new_password)
    user.auth_version = int(user.auth_version or 0) + 1
    audit(db, user, "password.changed", "user", user.id)
    db.commit()
    return {"changed": True}


@router.post("/api/v1/campaigns/{campaign_id}/duplicate", status_code=201)
def duplicate_campaign(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = db.get(Campaign, campaign_id)
    if not source:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role == UserRole.ADVERTISER and source.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot duplicate this campaign")
    advertiser_id = user.id if user.role == UserRole.ADVERTISER else source.advertiser_id
    clone = Campaign(
        advertiser_id=advertiser_id,
        package_id=source.package_id,
        title=f"{source.title} - Copy"[:160],
        caption=source.caption,
        media_url=source.media_url,
        destination_url=source.destination_url,
        preferred_publish_at=None,
        status=CampaignStatus.PAYMENT_PENDING,
    )
    db.add(clone)
    db.flush()
    audit(db, user, "campaign.duplicated", "campaign", clone.id, f"Copied from campaign {source.id}")
    db.commit()
    db.refresh(clone)
    return {"id": clone.id, "title": clone.title, "status": clone.status, "source_campaign_id": source.id}


@router.post("/api/v1/support/tickets", response_model=TicketOut, status_code=201)
def create_ticket(payload: TicketCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.campaign_id is not None:
        campaign = db.get(Campaign, payload.campaign_id)
        if not campaign or (user.role == UserRole.ADVERTISER and campaign.advertiser_id != user.id):
            raise HTTPException(status_code=404, detail="Campaign not found")
    ticket = SupportTicket(user_id=user.id, campaign_id=payload.campaign_id, subject=payload.subject.strip(), message=payload.message.strip())
    db.add(ticket)
    db.flush()
    audit(db, user, "support.ticket_created", "support_ticket", ticket.id)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/api/v1/support/tickets", response_model=list[TicketOut])
def list_tickets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(SupportTicket).order_by(SupportTicket.updated_at.desc())
    if user.role == UserRole.ADVERTISER:
        query = query.where(SupportTicket.user_id == user.id)
    return list(db.scalars(query))


@router.patch("/api/v1/support/tickets/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, payload: TicketUpdate, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    ticket.status = payload.status
    ticket.staff_reply = payload.staff_reply
    audit(db, staff, "support.ticket_updated", "support_ticket", ticket.id, payload.status.value)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.get("/api/v1/campaigns/{campaign_id}/performance/history", response_model=list[PerformanceHistoryOut])
def campaign_performance_history(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role == UserRole.ADVERTISER and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this campaign")
    return list(db.scalars(
        select(CampaignPerformanceSnapshot)
        .where(CampaignPerformanceSnapshot.campaign_id == campaign_id)
        .order_by(CampaignPerformanceSnapshot.captured_at.asc())
        .limit(365)
    ))


@router.get("/api/v1/advertiser/performance/history", response_model=list[PerformanceHistoryOut])
def advertiser_performance_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != UserRole.ADVERTISER:
        raise HTTPException(status_code=403, detail="Advertiser access required")
    return list(db.scalars(
        select(CampaignPerformanceSnapshot)
        .join(Campaign, Campaign.id == CampaignPerformanceSnapshot.campaign_id)
        .where(Campaign.advertiser_id == user.id)
        .order_by(CampaignPerformanceSnapshot.captured_at.asc())
        .limit(1000)
    ))


@router.post("/api/v1/profile/2fa/setup")
def setup_two_factor(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == UserRole.ADVERTISER:
        raise HTTPException(status_code=403, detail="Two-factor setup is currently required for Meloli staff accounts")
    secret = pyotp.random_base32()
    user.totp_secret = encrypt_secret(secret)
    user.two_factor_enabled = False
    audit(db, user, "two_factor.setup_started", "user", user.id)
    db.commit()
    issuer = "Meloli Airwaves"
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=issuer)
    return {"secret": secret, "otpauth_uri": uri, "enabled": False}


@router.post("/api/v1/profile/2fa/enable")
def enable_two_factor(payload: TwoFactorEnable, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.totp_secret:
        raise HTTPException(status_code=409, detail="Start two-factor setup first")
    secret = decrypt_secret(user.totp_secret)
    if not pyotp.TOTP(secret).verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    user.two_factor_enabled = True
    audit(db, user, "two_factor.enabled", "user", user.id)
    db.commit()
    return {"enabled": True}


@router.post("/api/v1/profile/2fa/disable")
def disable_two_factor(payload: TwoFactorDisable, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.two_factor_enabled or not user.totp_secret:
        return {"enabled": False}
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")
    secret = decrypt_secret(user.totp_secret)
    if not pyotp.TOTP(secret).verify(payload.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid authentication code")
    user.two_factor_enabled = False
    user.totp_secret = None
    audit(db, user, "two_factor.disabled", "user", user.id)
    db.commit()
    return {"enabled": False}


@router.post("/api/v1/profile/logout-all")
def logout_all_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.auth_version = int(user.auth_version or 0) + 1
    audit(db, user, "sessions.revoked_all", "user", user.id)
    db.commit()
    return {"message": "All existing sessions have been revoked. Sign in again on devices you want to keep using."}


@router.get("/api/v1/profile/security")
def security_status(user: User = Depends(current_user)):
    return {"two_factor_enabled": bool(user.two_factor_enabled), "staff_two_factor_available": user.role != UserRole.ADVERTISER}
