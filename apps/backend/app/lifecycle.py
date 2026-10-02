import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .communications import send_direct_email
from .db import get_db
from .models import AdvertiserSubscription, AuthSession, AuditLog, Campaign, CampaignStatus, CorporateAccount, CorporateCreditNote, CorporateInvoice, CorporateInvoiceLine, PasswordResetToken, Payment, PaymentStatus, RefundRequest, User, UserRole
from .security import validate_token_user, hash_password

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class ResetRequest(BaseModel):
    email: EmailStr


class ResetComplete(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    password: str = Field(min_length=10, max_length=128)


class RefundCreate(BaseModel):
    payment_id: int
    reason: str = Field(min_length=5, max_length=2000)


class CampaignCancel(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class RefundDecision(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    staff_note: str | None = Field(default=None, max_length=2000)


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


@router.post("/api/v1/auth/password-reset/request")
def request_password_reset(payload: ResetRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user and user.is_active:
        raw = secrets.token_urlsafe(48)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        db.add(PasswordResetToken(user_id=user.id, token_hash=digest, expires_at=now + timedelta(minutes=45)))
        audit(db, user, "password_reset.requested", "user", user.id)
        db.commit()
        base = os.getenv("FRONTEND_PUBLIC_URL", "http://localhost:3000").rstrip("/")
        try:
            send_direct_email(
                db,
                user.email,
                "Reset your Meloli Airwaves password",
                f"Hello {user.full_name},\n\nUse the link below to reset your Meloli Advertising Portal password. This link expires in 45 minutes and can only be used once.\n\n{base}/forgot-password?token={raw}\n\nIf you did not request this, you can ignore this email.\n\nMeloli Airwaves Advertising Portal",
            )
        except Exception:
            # Keep the public response non-enumerating; delivery failures are visible in server operations.
            pass
    return {"message": "If that email belongs to an active Meloli account, password reset instructions have been sent."}


@router.post("/api/v1/auth/password-reset/complete")
def complete_password_reset(payload: ResetComplete, db: Session = Depends(get_db)):
    digest = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == digest))
    now = datetime.now(timezone.utc)
    if not row or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Reset link is invalid or has already been used")
    expiry = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at.astimezone(timezone.utc)
    if expiry < now:
        raise HTTPException(status_code=400, detail="Reset link has expired")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Reset link is invalid")
    user.password_hash = hash_password(payload.password)
    user.auth_version = int(user.auth_version or 0) + 1
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        session.revoked_at = now
    row.used_at = now
    for token in db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))):
        token.used_at = now
    audit(db, user, "password_reset.completed", "user", user.id)
    db.commit()
    return {"message": "Password updated successfully. You can now sign in."}


@router.post("/api/v1/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: int, payload: CampaignCancel, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role == UserRole.ADVERTISER and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot cancel this campaign")
    if campaign.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Campaign is already cancelled")
    if campaign.status == CampaignStatus.PUBLISHED or campaign.published_at is not None:
        raise HTTPException(status_code=409, detail="Published campaigns cannot be cancelled through self-service")
    campaign.cancelled_at = datetime.now(timezone.utc)
    campaign.cancellation_reason = payload.reason.strip()
    campaign.cancelled_by_user_id = user.id
    campaign.scheduled_publish_at = None

    paid = db.scalar(
        select(Payment)
        .where(Payment.campaign_id == campaign.id, Payment.status == PaymentStatus.PAID)
        .order_by(Payment.created_at.desc())
    )
    refund_id = None
    if paid:
        existing = db.scalar(select(RefundRequest).where(RefundRequest.payment_id == paid.id, RefundRequest.status == "requested"))
        if existing:
            refund_id = existing.id
        else:
            refund = RefundRequest(
                payment_id=paid.id,
                user_id=campaign.advertiser_id,
                reason=f"Campaign cancelled: {payload.reason.strip()}",
            )
            db.add(refund)
            db.flush()
            refund_id = refund.id
    audit(db, user, "campaign.cancelled", "campaign", campaign.id, payload.reason.strip())
    db.commit()
    return {"id": campaign.id, "cancelled_at": campaign.cancelled_at, "refund_request_id": refund_id}


@router.post("/api/v1/refunds", status_code=201)
def request_refund(payload: RefundCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = db.get(Payment, payload.payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    campaign = db.get(Campaign, payment.campaign_id)
    if not campaign or (user.role == UserRole.ADVERTISER and campaign.advertiser_id != user.id):
        raise HTTPException(status_code=403, detail="You cannot request a refund for this payment")
    if payment.status != PaymentStatus.PAID:
        raise HTTPException(status_code=409, detail="Only confirmed payments can be refunded")
    if campaign.status == CampaignStatus.PUBLISHED:
        raise HTTPException(status_code=409, detail="Published campaigns require manual commercial review")
    existing = db.scalar(select(RefundRequest).where(RefundRequest.payment_id == payment.id, RefundRequest.status == "requested"))
    if existing:
        raise HTTPException(status_code=409, detail="A refund request is already open for this payment")
    row = RefundRequest(payment_id=payment.id, user_id=campaign.advertiser_id, reason=payload.reason.strip())
    db.add(row)
    db.flush()
    audit(db, user, "refund.requested", "refund_request", row.id, f"Payment {payment.id}")
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/api/v1/refunds")
def my_refunds(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(RefundRequest).order_by(RefundRequest.requested_at.desc())
    if user.role == UserRole.ADVERTISER:
        query = query.where(RefundRequest.user_id == user.id)
    rows = list(db.scalars(query.limit(200)))
    return [{"id":r.id,"payment_id":r.payment_id,"user_id":r.user_id,"reason":r.reason,"status":r.status,"staff_note":r.staff_note,"requested_at":r.requested_at,"decided_at":r.decided_at} for r in rows]


@router.post("/api/v1/admin/refunds/{refund_id}/decision")
def decide_refund(refund_id: int, payload: RefundDecision, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    row = db.get(RefundRequest, refund_id)
    if not row:
        raise HTTPException(status_code=404, detail="Refund request not found")
    if row.status != "requested":
        raise HTTPException(status_code=409, detail="Refund request has already been decided")
    payment = db.get(Payment, row.payment_id)
    campaign = db.get(Campaign, payment.campaign_id) if payment else None
    if not payment or not campaign:
        raise HTTPException(status_code=409, detail="Refund payment data is incomplete")
    row.status = payload.status
    row.staff_note = payload.staff_note
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by_user_id = admin.id
    if payload.status == "approved":
        payment.status = PaymentStatus.REFUNDED
        if payment.method == "corporate_credit":
            account = db.scalar(select(CorporateAccount).where(CorporateAccount.user_id == campaign.advertiser_id))
            if account:
                account.credit_used = max(0, float(account.credit_used) - float(payment.amount))
                invoice_line = db.scalar(select(CorporateInvoiceLine).where(CorporateInvoiceLine.payment_id == payment.id))
                invoice = db.get(CorporateInvoice, invoice_line.invoice_id) if invoice_line else None
                applied = min(float(payment.amount), float(invoice_line.amount)) if invoice_line else 0.0
                credit_note = CorporateCreditNote(
                    credit_note_number=f"CN-MEL-{row.id:06d}",
                    corporate_account_id=account.id,
                    invoice_id=invoice.id if invoice else None,
                    payment_id=payment.id,
                    refund_request_id=row.id,
                    amount=payment.amount,
                    applied_to_invoice_amount=applied,
                    currency=payment.currency,
                    reason=row.reason,
                    issued_by_user_id=admin.id,
                )
                db.add(credit_note)
                db.flush()
                if invoice:
                    total_credits = sum(
                        float(v or 0)
                        for v in db.scalars(
                            select(CorporateCreditNote.applied_to_invoice_amount)
                            .where(CorporateCreditNote.invoice_id == invoice.id)
                        )
                    )
                    effective = max(0.0, float(invoice.amount) - float(invoice.amount_paid) - total_credits)
                    if effective <= 0:
                        invoice.status = "credited" if float(invoice.amount_paid) == 0 and total_credits >= float(invoice.amount) else "closed"
                    else:
                        invoice.status = "partial"
        elif payment.method == "subscription":
            subscription = db.scalar(
                select(AdvertiserSubscription)
                .where(AdvertiserSubscription.user_id == campaign.advertiser_id)
                .order_by(AdvertiserSubscription.period_end.desc())
            )
            if subscription:
                subscription.remaining_posts += 1
        if campaign.status != CampaignStatus.PUBLISHED:
            campaign.status = CampaignStatus.PAYMENT_PENDING
        audit(db, admin, "refund.approved", "refund_request", row.id, f"Payment {payment.id}")
    else:
        audit(db, admin, "refund.rejected", "refund_request", row.id, f"Payment {payment.id}")
    db.commit()
    return {"id": row.id, "status": row.status}
