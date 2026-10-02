import io
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .branding import BORDER, LIGHT, MUTED, NAVY, RED, draw_footer, draw_header, info_label
from .db import get_db
from .models import AdvertisingPackage, AuditLog, Campaign, CampaignStatus, NotificationDelivery, Payment, PaymentStatus, PublicationAttempt, PublicationStatus, SystemSetting, User, UserRole
from .security import validate_token_user, hash_password

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
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


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


@router.get("/api/v1/admin/sla-summary")
def sla_summary(_: User = Depends(staff), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    review_hours = max(1, int(os.getenv("REVIEW_SLA_HOURS", "4")))
    proof_hours = max(1, int(os.getenv("PROOF_RESPONSE_TARGET_HOURS", "24")))
    review_cutoff = now - timedelta(hours=review_hours)
    proof_cutoff = now - timedelta(hours=proof_hours)

    review_rows = list(db.scalars(
        select(Campaign)
        .where(
            Campaign.cancelled_at.is_(None),
            Campaign.status.in_([CampaignStatus.SUBMITTED, CampaignStatus.IN_REVIEW]),
            Campaign.updated_at <= review_cutoff,
        )
        .order_by(Campaign.updated_at)
        .limit(100)
    ))
    proof_rows = list(db.scalars(
        select(Campaign)
        .where(
            Campaign.cancelled_at.is_(None),
            Campaign.proof_status == "pending_advertiser",
            Campaign.proof_requested_at.is_not(None),
            Campaign.proof_requested_at <= proof_cutoff,
        )
        .order_by(Campaign.proof_requested_at)
        .limit(100)
    ))
    publish_rows = list(db.scalars(
        select(Campaign)
        .where(
            Campaign.cancelled_at.is_(None),
            Campaign.status == CampaignStatus.SCHEDULED,
            Campaign.scheduled_publish_at.is_not(None),
            Campaign.scheduled_publish_at < now,
            Campaign.facebook_post_id.is_(None),
        )
        .order_by(Campaign.scheduled_publish_at)
        .limit(100)
    ))
    failed_notifications = db.scalar(
        select(func.count(NotificationDelivery.id)).where(NotificationDelivery.status == "failed")
    ) or 0

    advertiser_ids = {
        row.advertiser_id
        for row in [*review_rows, *proof_rows, *publish_rows]
    }
    advertisers = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_(advertiser_ids)))
    } if advertiser_ids else {}

    def item(row: Campaign, kind: str, due_at: datetime | None):
        point = due_at or row.updated_at or row.created_at
        point = point.replace(tzinfo=timezone.utc) if point and point.tzinfo is None else point
        age_hours = max(0.0, (now - point).total_seconds() / 3600) if point else 0.0
        advertiser = advertisers.get(row.advertiser_id)
        return {
            "campaign_id": row.id,
            "title": row.title,
            "advertiser_id": row.advertiser_id,
            "advertiser": (advertiser.business_name or advertiser.full_name) if advertiser else f"Advertiser #{row.advertiser_id}",
            "kind": kind,
            "status": row.status,
            "proof_status": row.proof_status,
            "age_hours": round(age_hours, 1),
            "due_at": due_at,
        }

    rows = [
        *[item(row, "review_overdue", row.updated_at) for row in review_rows],
        *[item(row, "proof_waiting", row.proof_requested_at) for row in proof_rows],
        *[item(row, "publish_overdue", row.scheduled_publish_at) for row in publish_rows],
    ]
    rows.sort(key=lambda row: row["age_hours"], reverse=True)
    return {
        "review_sla_hours": review_hours,
        "proof_response_target_hours": proof_hours,
        "review_overdue": len(review_rows),
        "proof_waiting": len(proof_rows),
        "publish_overdue": len(publish_rows),
        "failed_notifications": int(failed_notifications),
        "total_attention": len(rows) + int(failed_notifications),
        "rows": rows[:200],
        "checked_at": now,
    }


@router.get("/api/v1/admin/production-readiness")
def production_readiness(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    def setting(key: str) -> str | None:
        row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
        return row.value if row and not row.encrypted else ("configured" if row and row.value else None)

    checks = []
    def add(key: str, label: str, ok: bool, detail: str, severity: str = "critical"):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail, "severity": severity})

    jwt = os.getenv("JWT_SECRET", "")
    encryption = os.getenv("SETTINGS_ENCRYPTION_KEY", "")
    super_password = os.getenv("SUPER_ADMIN_PASSWORD", "")
    db_password = os.getenv("POSTGRES_PASSWORD", "")
    cors = os.getenv("CORS_ORIGINS", "")
    allowed_hosts = os.getenv("ALLOWED_HOSTS", "")
    public_backend = os.getenv("PUBLIC_BACKEND_URL", "")
    frontend_public = os.getenv("FRONTEND_PUBLIC_URL", "")

    add("jwt_secret", "JWT signing secret", len(jwt) >= 32 and "change-this" not in jwt.lower(), "Use an independent random JWT_SECRET of at least 32 characters.")
    add("settings_key", "Settings encryption key", len(encryption) >= 32 and "change-this" not in encryption.lower(), "Use an independent random SETTINGS_ENCRYPTION_KEY of at least 32 characters.")
    add("super_admin_password", "Super Admin bootstrap password", len(super_password) >= 12 and "change" not in super_password.lower(), "Set a strong deployment secret; do not use a repository/default password.")
    add("database_password", "Database password", len(db_password) >= 16 and db_password != "meloli_dev" and "change" not in db_password.lower(), "Set POSTGRES_PASSWORD to a strong production-only secret.")
    add("cors", "Production CORS origins", bool(cors) and "*" not in cors and "localhost" not in cors, f"Configured origins: {cors or 'not set'}")
    add("allowed_hosts", "Trusted host allowlist", bool(allowed_hosts) and "*" not in allowed_hosts and "localhost" not in allowed_hosts, f"Configured hosts: {allowed_hosts or 'not set'}")
    add("backend_https", "Public backend HTTPS", public_backend.startswith("https://"), public_backend or "PUBLIC_BACKEND_URL is not set")
    add("frontend_https", "Public frontend HTTPS", frontend_public.startswith("https://"), frontend_public or "FRONTEND_PUBLIC_URL is not set")
    add("meta", "Meta Page integration", setting("meta.connected") == "true", "Meta connection must pass Test connection in System Configuration.")
    email_enabled = setting("notifications.email_enabled") == "true"
    smtp_ready = bool(setting("notifications.smtp_host") and setting("notifications.from_email"))
    add("email", "Advertiser email delivery", email_enabled and smtp_ready, "Enable SMTP and configure host/from address for recovery, invoices and notifications.", "warning")

    backup_root = os.getenv("BACKUP_ROOT", "/data/backups")
    max_age = max(1, int(os.getenv("BACKUP_MAX_AGE_HOURS", "30")))
    backup_age = None
    try:
        freshness = os.path.join(backup_root, "last-success")
        if os.path.isfile(freshness):
            modified = datetime.fromtimestamp(os.path.getmtime(freshness), tz=timezone.utc)
            backup_age = round((datetime.now(timezone.utc) - modified).total_seconds() / 3600, 1)
    except OSError:
        pass
    add("backup", "Verified database/media backup", backup_age is not None and backup_age <= max_age, f"Latest verified backup age: {backup_age if backup_age is not None else 'none'} hours; maximum {max_age} hours.")

    critical_failed = [item for item in checks if item["severity"] == "critical" and not item["ok"]]
    warning_failed = [item for item in checks if item["severity"] == "warning" and not item["ok"]]
    return {
        "ready": len(critical_failed) == 0,
        "critical_failures": len(critical_failed),
        "warnings": len(warning_failed),
        "checks": checks,
        "checked_at": datetime.now(timezone.utc),
    }


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
    backup_root = os.getenv("BACKUP_ROOT", "/data/backups")
    backup_max_age_hours = max(1, int(os.getenv("BACKUP_MAX_AGE_HOURS", "30")))
    backup_last_success = None
    backup_age_hours = None
    backup_stale = True
    latest_db_backup = None
    latest_media_backup = None
    try:
        backup_files = [os.path.join(backup_root, name) for name in os.listdir(backup_root) if os.path.isfile(os.path.join(backup_root, name))]
        db_files = [path for path in backup_files if os.path.basename(path).startswith("db-") and path.endswith(".dump")]
        media_files = [path for path in backup_files if os.path.basename(path).startswith("media-") and path.endswith(".tar.gz")]
        latest_db_backup = max(db_files, key=os.path.getmtime) if db_files else None
        latest_media_backup = max(media_files, key=os.path.getmtime) if media_files else None
        freshness_path = os.path.join(backup_root, "last-success")
        if os.path.isfile(freshness_path):
            modified = datetime.fromtimestamp(os.path.getmtime(freshness_path), tz=timezone.utc)
            backup_last_success = modified
            backup_age_hours = round((datetime.now(timezone.utc) - modified).total_seconds() / 3600, 1)
            backup_stale = backup_age_hours > backup_max_age_hours
    except OSError:
        pass

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
        "backup_root": backup_root,
        "backup_last_success": backup_last_success,
        "backup_age_hours": backup_age_hours,
        "backup_max_age_hours": backup_max_age_hours,
        "backup_stale": backup_stale,
        "latest_db_backup": os.path.basename(latest_db_backup) if latest_db_backup else None,
        "latest_db_backup_bytes": os.path.getsize(latest_db_backup) if latest_db_backup else 0,
        "latest_media_backup": os.path.basename(latest_media_backup) if latest_media_backup else None,
        "latest_media_backup_bytes": os.path.getsize(latest_media_backup) if latest_media_backup else 0,
        "checked_at": datetime.now(timezone.utc),
    }


def _commercial_pdf(title: str, campaign: Campaign, package: AdvertisingPackage, advertiser: User, document_no: str, paid: bool = False, db: Session | None = None, amount: float | None = None, payment_method: str | None = None, payment_reference: str | None = None) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    pdf.setTitle(f"{title} {document_no}")
    status_text = "PAID" if paid else ("QUOTATION" if "quotation" in title.lower() else "PAYMENT DUE")
    document_amount = float(package.price) if amount is None else float(amount)
    draw_header(pdf, db, title, document_no, status_text) if db is not None else None

    top = height - 154
    # Client and document summary cards.
    pdf.setFillColor(LIGHT)
    pdf.roundRect(46, top - 92, width - 92, 92, 14, fill=1, stroke=0)
    info_label(pdf, 62, top - 22, "Bill to", advertiser.business_name or advertiser.full_name)
    info_label(pdf, 62, top - 58, "Email", advertiser.email)
    info_label(pdf, 305, top - 22, "Campaign", campaign.title, 42)
    info_label(pdf, 305, top - 58, "Generated", datetime.now(timezone.utc).strftime("%d %b %Y"))

    # Package / line-item table.
    y = top - 122
    pdf.setFillColor(NAVY)
    pdf.roundRect(46, y - 24, width - 92, 24, 8, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(58, y - 16, "DESCRIPTION")
    pdf.drawString(350, y - 16, "QTY")
    pdf.drawRightString(width - 58, y - 16, "AMOUNT")

    y -= 48
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(58, y, package.name)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.5)
    description = (package.description or "Meloli Airwaves advertising placement").replace("\n", " ")
    pdf.drawString(58, y - 15, description[:58])
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawCentredString(365, y, str(package.posts_included))
    pdf.drawRightString(width - 58, y, f"{package.currency} {document_amount:,.2f}")
    pdf.setStrokeColor(BORDER)
    pdf.line(46, y - 29, width - 46, y - 29)

    # Totals block.
    total_y = y - 67
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(width - 170, total_y, "Subtotal")
    pdf.drawRightString(width - 58, total_y, f"{package.currency} {document_amount:,.2f}")
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawRightString(width - 170, total_y - 28, "TOTAL")
    pdf.setFillColor(RED)
    pdf.drawRightString(width - 58, total_y - 28, f"{package.currency} {document_amount:,.2f}")

    # Campaign brief.
    brief_y = total_y - 72
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(46, brief_y, "CAMPAIGN BRIEF")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.5)
    text_obj = pdf.beginText(46, brief_y - 18)
    text_obj.setLeading(12)
    caption = (campaign.caption or "").replace("\n", " ")
    for i in range(0, min(len(caption), 720), 88):
        text_obj.textLine(caption[i:i + 88])
    pdf.drawText(text_obj)

    # Payment / validity note.
    note_y = 112
    pdf.setFillColor(colors.HexColor("#FFF1F4"))
    pdf.roundRect(46, note_y, width - 92, 48, 12, fill=1, stroke=0)
    pdf.setFillColor(RED)
    pdf.setFont("Helvetica-Bold", 8)
    note_title = "PAYMENT CONFIRMED" if paid else ("QUOTATION VALIDITY" if "quotation" in title.lower() else "PAYMENT INFORMATION")
    pdf.drawString(60, note_y + 31, note_title)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica", 8)
    if payment_method:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8)
        method_text = payment_method.replace("_", " ").title()
        ref_text = f" · Ref: {payment_reference}" if payment_reference else ""
        pdf.drawString(46, brief_y - 82, f"Payment method: {method_text}{ref_text}"[:92])

    note = "This document is marked paid in the Meloli portal." if paid else (
        "This quotation is issued for the selected campaign package and may be used for payment approval."
        if "quotation" in title.lower() else
        "Please use the campaign reference when making payment. Publication proceeds after payment verification and editorial approval."
    )
    pdf.drawString(60, note_y + 16, note[:92])

    draw_footer(pdf)
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
    data = _commercial_pdf("Advertising quotation", campaign, package, advertiser, f"Q-MEL-{campaign.id:06d}", db=db)
    audit(db, user, "quotation.generated", "campaign", campaign.id)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="meloli-quotation-{campaign.id}.pdf"'})


@router.get("/api/v1/campaigns/{campaign_id}/invoice.pdf")
def invoice(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign, package, advertiser = _document_context(db, campaign_id, user)
    latest_payment = db.scalar(select(Payment).where(Payment.campaign_id == campaign.id).order_by(Payment.created_at.desc()))
    paid = bool(latest_payment and latest_payment.status == PaymentStatus.PAID)
    data = _commercial_pdf(
        "Advertising invoice",
        campaign,
        package,
        advertiser,
        f"INV-MEL-{campaign.id:06d}",
        paid=paid,
        db=db,
        amount=float(latest_payment.amount) if latest_payment else None,
        payment_method=latest_payment.method if latest_payment else None,
        payment_reference=latest_payment.reference if latest_payment else None,
    )
    audit(db, user, "invoice.generated", "campaign", campaign.id)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="meloli-invoice-{campaign.id}.pdf"'})
