import io
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .db import get_db
from .models import AdvertisingPackage, AuditLog, Campaign, CampaignStatus, Payment, PaymentStatus, PublicationAttempt, PublicationStatus, User, UserRole
from .security import decode_access_token, hash_password

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class StaffCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: UserRole


class UserStateUpdate(BaseModel):
    is_active: bool


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = int(decode_access_token(credentials.credentials)["sub"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


def staff(user: User = Depends(current_user)) -> User:
    if user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Meloli staff access required")
    return user


def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: int | str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, detail=detail))


@router.get("/api/v1/admin/advertisers")
def advertisers(_: User = Depends(staff), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).where(User.role == UserRole.ADVERTISER).order_by(User.created_at.desc())))
    result = []
    for user in users:
        campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.advertiser_id == user.id)) or 0
        published = db.scalar(select(func.count(Campaign.id)).where(Campaign.advertiser_id == user.id, Campaign.status == CampaignStatus.PUBLISHED)) or 0
        spend = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Campaign, Campaign.id == Payment.campaign_id)
            .where(Campaign.advertiser_id == user.id, Payment.status == PaymentStatus.PAID)
        ) or 0
        result.append({
            "id": user.id,
            "full_name": user.full_name,
            "business_name": user.business_name,
            "email": user.email,
            "phone": user.phone,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "campaigns": int(campaigns),
            "published": int(published),
            "confirmed_spend": float(spend),
            "currency": "LSL",
        })
    return result


@router.patch("/api/v1/admin/users/{user_id}/state")
def set_user_state(user_id: int, payload: UserStateUpdate, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and not payload.is_active:
        raise HTTPException(status_code=409, detail="You cannot disable your own super-admin account")
    user.is_active = payload.is_active
    audit(db, admin, "user.activated" if payload.is_active else "user.disabled", "user", user.id, user.email)
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.get("/api/v1/admin/staff")
def list_staff(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(User).where(User.role != UserRole.ADVERTISER).order_by(User.created_at.desc())))
    return [{"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role, "is_active": u.is_active, "created_at": u.created_at} for u in rows]


@router.post("/api/v1/admin/staff", status_code=201)
def create_staff(payload: StaffCreate, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    if payload.role == UserRole.ADVERTISER:
        raise HTTPException(status_code=400, detail="Use advertiser registration for advertiser accounts")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user already exists for this email")
    user = User(full_name=payload.full_name, email=email, password_hash=hash_password(payload.password), role=payload.role)
    db.add(user)
    db.flush()
    audit(db, admin, "staff.created", "user", user.id, payload.role.value)
    db.commit()
    return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role, "is_active": user.is_active}


@router.get("/api/v1/admin/audit")
def audit_log(_: User = Depends(super_admin), db: Session = Depends(get_db), limit: int = 200):
    limit = max(1, min(limit, 1000))
    rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)))
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([r.actor_user_id for r in rows if r.actor_user_id is not None])))} if rows else {}
    return [{
        "id": r.id,
        "actor_user_id": r.actor_user_id,
        "actor": users.get(r.actor_user_id).full_name if r.actor_user_id in users else None,
        "action": r.action,
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "detail": r.detail,
        "created_at": r.created_at,
    } for r in rows]


@router.get("/api/v1/admin/system-health")
def system_health(_: User = Depends(staff), db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    media_root = os.getenv("MEDIA_ROOT", "/data/media")
    try:
        stat = os.statvfs(media_root)
        free_bytes = stat.f_frsize * stat.f_bavail
        total_bytes = stat.f_frsize * stat.f_blocks
    except OSError:
        free_bytes = total_bytes = 0
    failed = db.scalar(select(func.count(PublicationAttempt.id)).where(PublicationAttempt.status == PublicationStatus.FAILED)) or 0
    due = db.scalar(select(func.count(Campaign.id)).where(Campaign.status == CampaignStatus.SCHEDULED, Campaign.scheduled_publish_at <= datetime.now(timezone.utc))) or 0
    last_publish = db.scalar(select(func.max(Campaign.published_at)).where(Campaign.status == CampaignStatus.PUBLISHED))
    return {
        "status": "ok",
        "database": "ok",
        "media_root": media_root,
        "media_total_bytes": int(total_bytes),
        "media_free_bytes": int(free_bytes),
        "failed_publication_attempts": int(failed),
        "due_scheduled_campaigns": int(due),
        "last_published_at": last_publish,
        "worker_expected": os.getenv("PUBLISHER_WORKER_ENABLED", "true").lower() == "true",
        "checked_at": datetime.now(timezone.utc),
    }


def _commercial_pdf(title: str, campaign: Campaign, package: AdvertisingPackage, advertiser: User, document_no: str, paid: bool = False) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    pdf.setTitle(f"{title} {document_no}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, height - 60, "MELOLI AIRWAVES MEDIA")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(48, height - 78, title)
    pdf.line(48, height - 92, width - 48, height - 92)
    rows = [
        ("Document no.", document_no),
        ("Advertiser", advertiser.business_name or advertiser.full_name),
        ("Email", advertiser.email),
        ("Campaign", campaign.title),
        ("Package", package.name),
        ("Posts included", str(package.posts_included)),
        ("Amount", f"{package.currency} {float(package.price):,.2f}"),
        ("Status", "PAID" if paid else "PAYMENT PENDING"),
        ("Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
    ]
    y = height - 126
    for label, value in rows:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(48, y, label)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(165, y, str(value)[:80])
        y -= 23
    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(48, y, "Campaign caption")
    pdf.setFont("Helvetica", 9)
    text_obj = pdf.beginText(48, y - 18)
    text_obj.setLeading(13)
    caption = campaign.caption.replace("\n", " ")
    for i in range(0, min(len(caption), 900), 92):
        text_obj.textLine(caption[i:i + 92])
    pdf.drawText(text_obj)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(48, 42, "Generated by the Meloli Airwaves Advertising Portal.")
    pdf.save()
    return buffer.getvalue()


def _document_context(db: Session, campaign_id: int, user: User):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role == UserRole.ADVERTISER and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this campaign")
    package = db.get(AdvertisingPackage, campaign.package_id)
    advertiser = db.get(User, campaign.advertiser_id)
    if not package or not advertiser:
        raise HTTPException(status_code=409, detail="Campaign commercial data is incomplete")
    return campaign, package, advertiser


@router.get("/api/v1/campaigns/{campaign_id}/quotation.pdf")
def quotation(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign, package, advertiser = _document_context(db, campaign_id, user)
    data = _commercial_pdf("Advertising quotation", campaign, package, advertiser, f"Q-MEL-{campaign.id:06d}")
    audit(db, user, "quotation.generated", "campaign", campaign.id)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="meloli-quotation-{campaign.id}.pdf"'})


@router.get("/api/v1/campaigns/{campaign_id}/invoice.pdf")
def invoice(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign, package, advertiser = _document_context(db, campaign_id, user)
    paid = bool(db.scalar(select(func.count(Payment.id)).where(Payment.campaign_id == campaign.id, Payment.status == PaymentStatus.PAID)))
    data = _commercial_pdf("Advertising invoice", campaign, package, advertiser, f"INV-MEL-{campaign.id:06d}", paid=paid)
    audit(db, user, "invoice.generated", "campaign", campaign.id)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="meloli-invoice-{campaign.id}.pdf"'})
