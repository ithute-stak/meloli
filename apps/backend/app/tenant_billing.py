import hashlib
import io
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from .branding import LIGHT, MUTED, NAVY, draw_footer, draw_header
from .communications import enqueue_notification
from .db import get_db
from .models import (
    AuditLog,
    Tenant,
    TenantPlan,
    TenantSubscription,
    TenantSubscriptionInvoice,
    TenantSubscriptionPayment,
    User,
    UserRole,
)
from .security import validate_token_user
from .realtime import emit_realtime_event

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class TenantCheckoutCreate(BaseModel):
    plan_id: int
    billing_period: str = Field(default="monthly", pattern=r"^(monthly|annual)$")
    payment_method: str = Field(default="bank_transfer", min_length=2, max_length=80)
    payment_reference: str | None = Field(default=None, max_length=160)


class TenantPaymentConfirm(BaseModel):
    status: str = Field(default="paid", pattern=r"^(paid|rejected)$")
    reference: str | None = Field(default=None, max_length=160)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def tenant_admin(user: User = Depends(current_user)) -> User:
    if not user.is_tenant_admin or not user.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant administrator access required")
    return user


def platform_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Platform super admin access required")
    return user


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _price(plan: TenantPlan, billing_period: str) -> float:
    return float(plan.annual_price if billing_period == "annual" else plan.monthly_price)


def _period_end(start: datetime, billing_period: str) -> datetime:
    return start + timedelta(days=365 if billing_period == "annual" else 31)


def _invoice_payload(row: TenantSubscriptionInvoice, payment: TenantSubscriptionPayment | None, plan: TenantPlan | None) -> dict:
    return {
        "id": row.id,
        "invoice_number": row.invoice_number,
        "tenant_id": row.tenant_id,
        "plan_id": row.plan_id,
        "plan_name": plan.name if plan else None,
        "billing_period": row.billing_period,
        "amount": float(row.amount),
        "currency": row.currency,
        "status": row.status,
        "due_at": row.due_at,
        "paid_at": row.paid_at,
        "created_at": row.created_at,
        "payment": None if payment is None else {
            "id": payment.id,
            "amount": float(payment.amount),
            "currency": payment.currency,
            "method": payment.method,
            "reference": payment.reference,
            "status": payment.status,
            "verification_code": payment.verification_code,
            "paid_at": payment.paid_at,
        },
    }


def _invoice_for_user(db: Session, invoice_id: int, user: User) -> TenantSubscriptionInvoice:
    row = db.get(TenantSubscriptionInvoice, invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tenant subscription invoice not found")
    if user.role != UserRole.SUPER_ADMIN and row.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Invoice belongs to another portal")
    return row


def _render_invoice_pdf(db: Session, invoice: TenantSubscriptionInvoice) -> bytes:
    tenant = db.get(Tenant, invoice.tenant_id)
    plan = db.get(TenantPlan, invoice.plan_id)
    payment = db.scalar(select(TenantSubscriptionPayment).where(TenantSubscriptionPayment.invoice_id == invoice.id).order_by(TenantSubscriptionPayment.id.desc()))
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    draw_header(pdf, db, "Platform subscription invoice", invoice.invoice_number, invoice.status.upper(), tenant_id=invoice.tenant_id)
    y = height - 160
    pdf.setFillColor(NAVY); pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(55, y, tenant.name if tenant else f"Tenant #{invoice.tenant_id}")
    y -= 24
    pdf.setFont("Helvetica", 9); pdf.setFillColor(MUTED)
    pdf.drawString(55, y, f"Plan: {plan.name if plan else 'Subscription plan'}")
    y -= 15
    pdf.drawString(55, y, f"Billing period: {invoice.billing_period.title()}")
    y -= 15
    pdf.drawString(55, y, f"Due: {_as_utc(invoice.due_at).strftime('%d %b %Y')}")
    y -= 30
    pdf.setFillColor(LIGHT); pdf.roundRect(50, y - 88, width - 100, 88, 12, fill=1, stroke=0)
    pdf.setFillColor(NAVY); pdf.setFont("Helvetica", 9)
    pdf.drawString(65, y - 26, "PLATFORM SUBSCRIPTION")
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawRightString(width - 65, y - 30, f"{invoice.currency} {float(invoice.amount):,.2f}")
    pdf.setFont("Helvetica", 8); pdf.setFillColor(MUTED)
    pdf.drawString(65, y - 56, "This charge is for use of the multi-tenant advertising platform, separate from advertiser campaign payments.")
    y -= 120
    if payment:
        pdf.setFillColor(NAVY); pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(55, y, "Payment submission")
        y -= 18
        pdf.setFont("Helvetica", 9); pdf.setFillColor(MUTED)
        pdf.drawString(55, y, f"Method: {payment.method.replace('_', ' ').title()}")
        y -= 14
        pdf.drawString(55, y, f"Reference: {payment.reference or 'Pending reference'}")
        y -= 14
        pdf.drawString(55, y, f"Status: {payment.status.title()}")
    draw_footer(pdf, db, invoice.tenant_id)
    pdf.save()
    return buffer.getvalue()


def _render_receipt_pdf(db: Session, payment: TenantSubscriptionPayment) -> bytes:
    invoice = db.get(TenantSubscriptionInvoice, payment.invoice_id)
    tenant = db.get(Tenant, payment.tenant_id)
    plan = db.get(TenantPlan, invoice.plan_id) if invoice else None
    if not invoice or payment.status != "paid":
        raise HTTPException(status_code=409, detail="Only confirmed subscription payments have receipts")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    receipt_no = f"TSR-{payment.id:06d}"
    draw_header(pdf, db, "Platform subscription receipt", receipt_no, "PAID", tenant_id=payment.tenant_id)
    y = height - 160
    pdf.setFillColor(NAVY); pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(55, y, tenant.name if tenant else f"Tenant #{payment.tenant_id}")
    y -= 26
    pdf.setFillColor(LIGHT); pdf.roundRect(50, y - 95, width - 100, 95, 12, fill=1, stroke=0)
    pdf.setFillColor(NAVY); pdf.setFont("Helvetica", 9)
    pdf.drawString(65, y - 25, "AMOUNT RECEIVED")
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawRightString(width - 65, y - 31, f"{payment.currency} {float(payment.amount):,.2f}")
    pdf.setFont("Helvetica", 8); pdf.setFillColor(MUTED)
    pdf.drawString(65, y - 58, f"Plan: {plan.name if plan else 'Subscription'} · {invoice.billing_period.title()}")
    pdf.drawString(65, y - 73, f"Invoice: {invoice.invoice_number}")
    y -= 125
    pdf.setFillColor(NAVY); pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(55, y, "Payment details")
    y -= 18
    pdf.setFont("Helvetica", 9); pdf.setFillColor(MUTED)
    pdf.drawString(55, y, f"Paid: {_as_utc(payment.paid_at or datetime.now(timezone.utc)).strftime('%d %b %Y %H:%M UTC')}")
    y -= 14
    pdf.drawString(55, y, f"Method: {payment.method.replace('_', ' ').title()}")
    y -= 14
    pdf.drawString(55, y, f"Reference: {payment.reference or '—'}")
    y -= 14
    pdf.drawString(55, y, f"Verification code: {payment.verification_code or '—'}")
    y -= 28
    pdf.setFont("Helvetica", 8)
    pdf.drawString(55, y, "This receipt confirms payment for the Page tenant's platform subscription.")
    draw_footer(pdf, db, payment.tenant_id)
    pdf.save()
    return buffer.getvalue()


def _activate_subscription(db: Session, invoice: TenantSubscriptionInvoice, payment: TenantSubscriptionPayment, admin: User) -> TenantSubscription:
    plan = db.get(TenantPlan, invoice.plan_id)
    tenant = db.get(Tenant, invoice.tenant_id)
    if not plan or not tenant:
        raise HTTPException(status_code=409, detail="Subscription billing data is incomplete")
    now = datetime.now(timezone.utc)
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id))
    if subscription is None:
        subscription = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            current_period_start=now,
            current_period_end=_period_end(now, invoice.billing_period),
        )
        db.add(subscription)
    subscription.plan_id = plan.id
    subscription.status = "active"
    subscription.billing_period = invoice.billing_period
    subscription.price_amount = invoice.amount
    subscription.currency = invoice.currency
    subscription.current_period_start = now
    subscription.current_period_end = _period_end(now, invoice.billing_period)
    subscription.trial_ends_at = None
    subscription.reminder_stage = None
    tenant.active = True
    invoice.status = "paid"
    invoice.paid_at = now
    payment.status = "paid"
    payment.paid_at = now
    payment.confirmed_by_user_id = admin.id
    payment.verification_code = hashlib.sha256(
        f"{payment.id}:{invoice.invoice_number}:{payment.amount}:{now.isoformat()}:{secrets.token_hex(8)}".encode("utf-8")
    ).hexdigest()[:20].upper()
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.subscription_payment_confirmed", entity_type="tenant_subscription_payment", entity_id=str(payment.id), detail=invoice.invoice_number))
    owner = db.scalar(select(User).where(User.tenant_id == tenant.id, User.is_tenant_admin.is_(True)).order_by(User.id))
    if owner:
        enqueue_notification(
            db,
            owner.id,
            "tenant_subscription_paid",
            f"{tenant.name} subscription activated",
            f"Payment for {plan.name} was confirmed. Your {invoice.billing_period} platform subscription is active until {subscription.current_period_end.strftime('%d %b %Y')}.",
        )
    return subscription


@router.get("/api/v1/tenant-plans")
def public_tenant_plans(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(TenantPlan).where(TenantPlan.active.is_(True)).order_by(TenantPlan.monthly_price, TenantPlan.id)))
    return [{
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "monthly_price": float(row.monthly_price),
        "annual_price": float(row.annual_price),
        "currency": row.currency,
        "max_staff": row.max_staff,
        "max_campaigns_monthly": row.max_campaigns_monthly,
        "custom_domains": row.custom_domains,
        "competition_certification": row.competition_certification,
    } for row in rows]


@router.get("/api/v1/tenant-admin/billing")
def tenant_billing(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    invoices = list(db.scalars(select(TenantSubscriptionInvoice).where(TenantSubscriptionInvoice.tenant_id == admin.tenant_id).order_by(TenantSubscriptionInvoice.created_at.desc()).limit(100)))
    result = []
    for row in invoices:
        payment = db.scalar(select(TenantSubscriptionPayment).where(TenantSubscriptionPayment.invoice_id == row.id).order_by(TenantSubscriptionPayment.id.desc()))
        result.append(_invoice_payload(row, payment, db.get(TenantPlan, row.plan_id)))
    return result


@router.post("/api/v1/tenant-admin/billing/checkout", status_code=201)
def create_checkout(payload: TenantCheckoutCreate, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    plan = db.get(TenantPlan, payload.plan_id)
    if not plan or not plan.active:
        raise HTTPException(status_code=400, detail="Tenant plan is unavailable")
    amount = _price(plan, payload.billing_period)
    now = datetime.now(timezone.utc)
    invoice = TenantSubscriptionInvoice(
        tenant_id=admin.tenant_id,
        plan_id=plan.id,
        invoice_number=f"TSI-{now:%Y%m%d}-{admin.tenant_id:04d}-{secrets.token_hex(3).upper()}",
        billing_period=payload.billing_period,
        amount=amount,
        currency=plan.currency,
        status="issued",
        due_at=now + timedelta(days=7),
        created_by_user_id=admin.id,
    )
    db.add(invoice); db.flush()
    payment = TenantSubscriptionPayment(
        invoice_id=invoice.id,
        tenant_id=admin.tenant_id,
        amount=amount,
        currency=plan.currency,
        method=payload.payment_method,
        reference=payload.payment_reference,
        status="pending",
    )
    db.add(payment); db.flush()
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.subscription_checkout_created", entity_type="tenant_subscription_invoice", entity_id=str(invoice.id), detail=plan.code))
    emit_realtime_event(
        db, "tenant_billing.checkout_created", tenant_id=admin.tenant_id, audience="platform_admins",
        entity_type="tenant_subscription_invoice", entity_id=invoice.id,
        payload={"invoice_id": invoice.id, "tenant_id": admin.tenant_id, "amount": float(amount), "currency": plan.currency, "plan": plan.code},
    )
    db.commit()
    if amount <= 0:
        _activate_subscription(db, invoice, payment, admin)
        db.commit()
    return _invoice_payload(invoice, payment, plan)


@router.get("/api/v1/admin/tenant-billing")
def admin_billing(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    invoices = list(db.scalars(select(TenantSubscriptionInvoice).order_by(TenantSubscriptionInvoice.created_at.desc()).limit(250)))
    result = []
    for row in invoices:
        payment = db.scalar(select(TenantSubscriptionPayment).where(TenantSubscriptionPayment.invoice_id == row.id).order_by(TenantSubscriptionPayment.id.desc()))
        tenant = db.get(Tenant, row.tenant_id)
        item = _invoice_payload(row, payment, db.get(TenantPlan, row.plan_id))
        item["tenant_name"] = tenant.name if tenant else None
        result.append(item)
    return result


@router.post("/api/v1/admin/tenant-billing/payments/{payment_id}/confirm")
def confirm_payment(payment_id: int, payload: TenantPaymentConfirm, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    payment = db.get(TenantSubscriptionPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Tenant subscription payment not found")
    if payment.status == "paid":
        raise HTTPException(status_code=409, detail="Payment is already confirmed")
    invoice = db.get(TenantSubscriptionInvoice, payment.invoice_id)
    if not invoice:
        raise HTTPException(status_code=409, detail="Subscription invoice is missing")
    if payload.reference:
        payment.reference = payload.reference.strip()
    if payload.status == "rejected":
        payment.status = "rejected"
        invoice.status = "payment_rejected"
        db.add(AuditLog(actor_user_id=admin.id, action="tenant.subscription_payment_rejected", entity_type="tenant_subscription_payment", entity_id=str(payment.id), detail=payment.reference))
        emit_realtime_event(
            db, "tenant_billing.payment_rejected", tenant_id=payment.tenant_id, audience="tenant_all",
            entity_type="tenant_subscription_payment", entity_id=payment.id,
            payload={"payment_id": payment.id, "invoice_id": invoice.id, "status": "rejected"},
        )
        emit_realtime_event(
            db, "tenant_billing.payment_rejected", tenant_id=payment.tenant_id, audience="platform_admins",
            entity_type="tenant_subscription_payment", entity_id=payment.id,
            payload={"payment_id": payment.id, "invoice_id": invoice.id, "status": "rejected"},
        )
        db.commit()
        return _invoice_payload(invoice, payment, db.get(TenantPlan, invoice.plan_id))
    subscription = _activate_subscription(db, invoice, payment, admin)
    emit_realtime_event(
        db, "tenant_billing.subscription_activated", tenant_id=payment.tenant_id, audience="tenant_all",
        entity_type="tenant_subscription", entity_id=subscription.id,
        payload={"subscription_id": subscription.id, "plan_id": subscription.plan_id, "status": subscription.status, "current_period_end": subscription.current_period_end},
    )
    emit_realtime_event(
        db, "tenant_billing.subscription_activated", tenant_id=payment.tenant_id, audience="platform_admins",
        entity_type="tenant_subscription", entity_id=subscription.id,
        payload={"subscription_id": subscription.id, "tenant_id": payment.tenant_id, "plan_id": subscription.plan_id, "status": subscription.status},
    )
    db.commit()
    return _invoice_payload(invoice, payment, db.get(TenantPlan, invoice.plan_id))


@router.get("/api/v1/tenant-billing/invoices/{invoice_id}.pdf")
def invoice_pdf(invoice_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    invoice = _invoice_for_user(db, invoice_id, user)
    data = _render_invoice_pdf(db, invoice)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_number}.pdf"'})


@router.get("/api/v1/tenant-billing/payments/{payment_id}/receipt.pdf")
def receipt_pdf(payment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = db.get(TenantSubscriptionPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Tenant subscription payment not found")
    if user.role != UserRole.SUPER_ADMIN and payment.tenant_id != user.tenant_id:
        raise HTTPException(status_code=403, detail="Receipt belongs to another portal")
    data = _render_receipt_pdf(db, payment)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="TSR-{payment.id:06d}.pdf"'})


def process_tenant_subscription_lifecycle(db: Session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    grace_days = max(0, int(os.getenv("TENANT_SUBSCRIPTION_GRACE_DAYS", "7")))
    warned = past_due = suspended = 0
    rows = list(db.scalars(select(TenantSubscription)))
    for subscription in rows:
        tenant = db.get(Tenant, subscription.tenant_id)
        if not tenant:
            continue
        end = _as_utc(subscription.current_period_end)
        owner = db.scalar(select(User).where(User.tenant_id == tenant.id, User.is_tenant_admin.is_(True)).order_by(User.id))
        delta_days = (end - now).total_seconds() / 86400

        target_stage = None
        if subscription.status in {"trialing", "active"} and delta_days > 0:
            if delta_days <= 1:
                target_stage = "1d"
            elif delta_days <= 3:
                target_stage = "3d"
            elif delta_days <= 7:
                target_stage = "7d"
            if target_stage and subscription.reminder_stage != target_stage:
                subscription.reminder_stage = target_stage
                warned += 1
                if owner:
                    enqueue_notification(
                        db,
                        owner.id,
                        "tenant_subscription_expiring",
                        f"{tenant.name} subscription expires soon",
                        f"Your platform subscription expires on {end.strftime('%d %b %Y')}. Renew it to keep campaigns, staff access and custom-domain routing active.",
                    )
        elif delta_days <= 0 and delta_days > -grace_days:
            if subscription.status != "past_due":
                subscription.status = "past_due"
                subscription.reminder_stage = "past_due"
                past_due += 1
                if owner:
                    enqueue_notification(
                        db,
                        owner.id,
                        "tenant_subscription_past_due",
                        f"{tenant.name} subscription is past due",
                        f"Your subscription expired on {end.strftime('%d %b %Y')}. A {grace_days}-day grace period is active before the Page portal is suspended.",
                    )
        elif delta_days <= -grace_days and subscription.status != "suspended":
            subscription.status = "suspended"
            subscription.reminder_stage = "suspended"
            tenant.active = False
            suspended += 1
            if owner:
                enqueue_notification(
                    db,
                    owner.id,
                    "tenant_subscription_suspended",
                    f"{tenant.name} portal suspended",
                    "The tenant subscription grace period ended. The Page portal is suspended until a subscription payment is confirmed.",
                )
            db.add(AuditLog(actor_user_id=None, action="tenant.subscription_suspended", entity_type="tenant", entity_id=str(tenant.id), detail=f"Expired {end.isoformat()}"))
            emit_realtime_event(
                db, "tenant.subscription_suspended", tenant_id=tenant.id, audience="tenant_all",
                entity_type="tenant", entity_id=tenant.id,
                payload={"tenant_id": tenant.id, "status": "suspended", "expired_at": end},
            )
            emit_realtime_event(
                db, "tenant.subscription_suspended", tenant_id=tenant.id, audience="platform_admins",
                entity_type="tenant", entity_id=tenant.id,
                payload={"tenant_id": tenant.id, "status": "suspended", "expired_at": end},
            )
    db.commit()
    return {"warned": warned, "past_due": past_due, "suspended": suspended}
