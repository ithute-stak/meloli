from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Campaign, Payment, PaymentStatus, ReferralAttribution, ReferralPartner, ReferralPayout, User, UserRole
from .security import validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class PartnerWrite(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    code: str = Field(min_length=2, max_length=50)
    commission_percent: float = Field(default=0, ge=0, le=100)
    contact_email: EmailStr | None = None
    active: bool = True


class PayoutWrite(BaseModel):
    amount: float = Field(gt=0)
    reference: str | None = Field(default=None, max_length=160)


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


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: int | str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, detail=detail))


@router.post("/api/v1/admin/referral-partners", status_code=201)
def create_partner(payload: PartnerWrite, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    code = payload.code.strip().upper()
    if db.scalar(select(ReferralPartner.id).where(ReferralPartner.code == code)):
        raise HTTPException(status_code=409, detail="Referral partner code already exists")
    row = ReferralPartner(
        name=payload.name.strip(),
        code=code,
        commission_percent=payload.commission_percent,
        contact_email=str(payload.contact_email) if payload.contact_email else None,
        active=payload.active,
        created_by_user_id=admin.id,
    )
    db.add(row); db.flush()
    audit(db, admin, "referral_partner.created", "referral_partner", row.id, code)
    db.commit(); db.refresh(row)
    return {"id":row.id,"name":row.name,"code":row.code,"commission_percent":float(row.commission_percent),"contact_email":row.contact_email,"active":row.active}


def _partner_metrics(db: Session, partner: ReferralPartner) -> dict:
    user_ids = list(db.scalars(select(ReferralAttribution.user_id).where(ReferralAttribution.partner_id == partner.id)))
    revenue = Decimal("0.00")
    paid_transactions = 0
    if user_ids:
        payments = list(db.scalars(
            select(Payment)
            .join(Campaign, Campaign.id == Payment.campaign_id)
            .where(Campaign.advertiser_id.in_(user_ids), Payment.status == PaymentStatus.PAID)
        ))
        paid_transactions = len(payments)
        revenue = sum((Decimal(str(p.amount)) for p in payments), Decimal("0.00"))
    commission = (revenue * Decimal(str(partner.commission_percent or 0)) / Decimal("100")).quantize(Decimal("0.01"))
    payouts = sum((Decimal(str(v)) for v in db.scalars(select(ReferralPayout.amount).where(ReferralPayout.partner_id == partner.id))), Decimal("0.00"))
    return {
        "id": partner.id,
        "name": partner.name,
        "code": partner.code,
        "commission_percent": float(partner.commission_percent),
        "contact_email": partner.contact_email,
        "active": partner.active,
        "referred_advertisers": len(user_ids),
        "paid_transactions": paid_transactions,
        "attributed_revenue": float(revenue),
        "commission_earned": float(commission),
        "commission_paid": float(payouts),
        "commission_due": float(max(Decimal("0.00"), commission - payouts)),
        "created_at": partner.created_at,
    }


@router.get("/api/v1/admin/referral-partners")
def list_partners(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(ReferralPartner).order_by(ReferralPartner.created_at.desc())))
    return [_partner_metrics(db, row) for row in rows]


@router.post("/api/v1/admin/referral-partners/{partner_id}/payouts", status_code=201)
def record_partner_payout(partner_id: int, payload: PayoutWrite, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    partner = db.get(ReferralPartner, partner_id)
    if not partner:
        raise HTTPException(status_code=404, detail="Referral partner not found")
    metrics = _partner_metrics(db, partner)
    if payload.amount > metrics["commission_due"] + 0.005:
        raise HTTPException(status_code=400, detail="Payout cannot exceed commission currently due")
    row = ReferralPayout(partner_id=partner.id, amount=payload.amount, reference=payload.reference, recorded_by_user_id=admin.id)
    db.add(row); db.flush()
    audit(db, admin, "referral_partner.payout_recorded", "referral_payout", row.id, f"{partner.code}; LSL {payload.amount:.2f}")
    db.commit()
    return {"id":row.id,"partner_id":partner.id,"amount":float(row.amount),"reference":row.reference,"paid_at":row.paid_at}


@router.get("/api/v1/admin/growth/forecast")
def growth_forecast(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=90)
    payments = list(db.scalars(
        select(Payment)
        .where(Payment.status == PaymentStatus.PAID, Payment.paid_at.is_not(None), Payment.paid_at >= cutoff)
        .order_by(Payment.paid_at)
    ))
    total_90 = sum((Decimal(str(p.amount)) for p in payments), Decimal("0.00"))
    monthly_run_rate = (total_90 / Decimal("3")).quantize(Decimal("0.01"))
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_to_date = sum((Decimal(str(p.amount)) for p in payments if p.paid_at and (p.paid_at.replace(tzinfo=timezone.utc) if p.paid_at.tzinfo is None else p.paid_at) >= current_month_start), Decimal("0.00"))
    elapsed_days = max(1, now.day)
    days_in_run_rate_month = Decimal("30")
    mtd_run_rate = (month_to_date / Decimal(elapsed_days) * days_in_run_rate_month).quantize(Decimal("0.01"))
    blended = ((monthly_run_rate + mtd_run_rate) / Decimal("2")).quantize(Decimal("0.01"))
    return {
        "currency": "LSL",
        "method": "50% trailing-90-day monthly run rate + 50% current-month pace",
        "trailing_90_day_revenue": float(total_90),
        "trailing_monthly_run_rate": float(monthly_run_rate),
        "month_to_date_revenue": float(month_to_date),
        "current_month_pace": float(mtd_run_rate),
        "forecast_next_30_days": float(blended),
        "forecast_next_90_days": float(blended * Decimal("3")),
        "generated_at": now,
    }
