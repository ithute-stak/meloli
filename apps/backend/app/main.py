import io
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .branding import LIGHT, MUTED, NAVY, RED, draw_footer, draw_header, info_label, tenant_brand
from .db import Base, SessionLocal, engine, get_db
from .commercial import discounted_amount, promo_for_code
from .communications import enqueue_notification
from .media import router as media_router
from .meta_service import MetaError, publish_campaign as publish_to_meta, verify_page
from .models import (
    AdvertiserSubscription,
    AuthSession,
    AdvertisingPackage,
    AuditLog,
    CorporateAccount,
    Campaign,
    CampaignMedia,
    CampaignReviewChecklist,
    CampaignStatus,
    Notification,
    Payment,
    PaymentStatus,
    PublicationAttempt,
    PublicationStatus,
    ReferralAttribution,
    ReferralPartner,
    SystemSetting,
    Tenant,
    TenantPlan,
    TenantSubscription,
    User,
    UserRole,
)
from .schemas import (
    AuthToken,
    CampaignCreate,
    CampaignDecision,
    CampaignOut,
    MetaIntegrationStatus,
    MetaIntegrationUpdate,
    NotificationOut,
    PackageOut,
    PackageWrite,
    PaymentCreate,
    PaymentDecision,
    PaymentOut,
    PublicationOut,
    PublishResult,
    ReportSummary,
    UserLogin,
    UserOut,
    UserRegister,
)
from .security import create_access_token, validate_token_user, decrypt_secret, encrypt_secret, hash_password, verify_password
from .realtime import emit_realtime_event
import pyotp

bearer = HTTPBearer(auto_error=False)

DEFAULT_PACKAGES = [
    {"code": "STANDARD", "name": "Standard Post", "description": "One approved Facebook Page post on the Meloli Airwaves publishing schedule.", "price": 450, "posts_included": 1},
    {"code": "PREMIUM", "name": "Premium Placement", "description": "One priority-scheduled promotional post with enhanced editorial placement.", "price": 650, "posts_included": 1},
    {"code": "WEEKLY", "name": "Weekly Campaign", "description": "A coordinated week-long package containing up to four approved posts.", "price": 1800, "posts_included": 4},
]


def seed_data() -> None:
    db = SessionLocal()
    try:
        default_tenant = db.scalar(select(Tenant).where(Tenant.slug == "meloli-airwaves"))
        if default_tenant is None:
            default_tenant = Tenant(
                name="Meloli Airwaves",
                slug="meloli-airwaves",
                facebook_page_name="Meloli Airwaves",
                accent_color="#e31545",
                active=True,
            )
            db.add(default_tenant)
            db.flush()
        for package_data in DEFAULT_PACKAGES:
            exists = db.scalar(
                select(AdvertisingPackage).where(
                    AdvertisingPackage.tenant_id == default_tenant.id,
                    AdvertisingPackage.code == package_data["code"],
                )
            )
            if not exists:
                db.add(AdvertisingPackage(tenant_id=default_tenant.id, **package_data))

        tenant_plan_defaults = [
            {
                "code": "STARTER",
                "name": "Starter",
                "description": "For smaller Facebook Pages starting to manage advertising clients.",
                "monthly_price": 299,
                "annual_price": 2990,
                "max_staff": 2,
                "max_campaigns_monthly": 50,
                "custom_domains": False,
                "competition_certification": False,
            },
            {
                "code": "BUSINESS",
                "name": "Business",
                "description": "For established Pages running regular campaigns, competitions and branded portals.",
                "monthly_price": 699,
                "annual_price": 6990,
                "max_staff": 8,
                "max_campaigns_monthly": 300,
                "custom_domains": True,
                "competition_certification": True,
            },
            {
                "code": "ENTERPRISE",
                "name": "Enterprise",
                "description": "Higher-capacity Page operations with larger teams and campaign volumes.",
                "monthly_price": 1499,
                "annual_price": 14990,
                "max_staff": 30,
                "max_campaigns_monthly": 2000,
                "custom_domains": True,
                "competition_certification": True,
            },
        ]
        for plan_data in tenant_plan_defaults:
            if not db.scalar(select(TenantPlan).where(TenantPlan.code == plan_data["code"])):
                db.add(TenantPlan(currency="LSL", active=True, **plan_data))
        db.flush()
        if not db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == default_tenant.id)):
            business_plan = db.scalar(select(TenantPlan).where(TenantPlan.code == "BUSINESS"))
            if business_plan:
                now = datetime.now(timezone.utc)
                db.add(TenantSubscription(
                    tenant_id=default_tenant.id,
                    plan_id=business_plan.id,
                    status="active",
                    billing_period="monthly",
                    price_amount=business_plan.monthly_price,
                    currency=business_plan.currency,
                    current_period_start=now,
                    current_period_end=now + timedelta(days=31),
                ))
        admin_email = os.getenv("SUPER_ADMIN_EMAIL")
        admin_password = os.getenv("SUPER_ADMIN_PASSWORD")
        if admin_email and admin_password and not db.scalar(select(User).where(User.email == admin_email.lower())):
            db.add(User(full_name=os.getenv("SUPER_ADMIN_NAME", "Meloli Super Admin"), email=admin_email.lower(), password_hash=hash_password(admin_password), role=UserRole.SUPER_ADMIN))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Alembic is the deployment migration mechanism. create_all is retained as a
    # local/test safety net and is idempotent against an already migrated schema.
    Base.metadata.create_all(bind=engine)
    seed_data()
    yield


app = FastAPI(title="Meloli Advertising API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
allowed_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "*").split(",") if h.strip()]
if allowed_hosts and allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
app.include_router(media_router)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User | None:
    if credentials is None:
        return None
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def package_admin(user: User = Depends(current_user)) -> User:
    if not user.is_tenant_admin and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Package administrator access required")
    return user


def staff_user(user: User = Depends(current_user)) -> User:
    if not user.is_tenant_admin and user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Portal staff access required")
    return user


def publisher_user(user: User = Depends(current_user)) -> User:
    if not user.is_tenant_admin and user.role not in {UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Publisher or portal admin access required")
    return user


def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def audit(db: Session, actor: User | None, action: str, entity_type: str, entity_id: int | str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor.id if actor else None, action=action, entity_type=entity_type, entity_id=str(entity_id) if entity_id is not None else None, detail=detail))


def notify(db: Session, user_id: int, kind: str, title: str, message: str) -> None:
    enqueue_notification(db, user_id, kind, title, message)


def get_setting(db: Session, key: str) -> SystemSetting | None:
    return db.scalar(select(SystemSetting).where(SystemSetting.key == key))


def setting_value(db: Session, key: str) -> str | None:
    item = get_setting(db, key)
    return item.value if item and not item.encrypted else None


def setting_secret(db: Session, key: str) -> str | None:
    item = get_setting(db, key)
    if not item or not item.value:
        return None
    return decrypt_secret(item.value) if item.encrypted else item.value


def set_setting(db: Session, key: str, value: str | None, encrypted: bool = False) -> None:
    item = get_setting(db, key)
    stored = encrypt_secret(value) if encrypted and value is not None else value
    if item:
        item.value = stored
        item.encrypted = encrypted
    else:
        db.add(SystemSetting(key=key, value=stored, encrypted=encrypted))


def meta_status(db: Session) -> MetaIntegrationStatus:
    def present(key: str) -> bool:
        item = get_setting(db, key)
        return bool(item and item.value)

    tracked = [get_setting(db, key) for key in ("meta.app_id", "meta.page_id", "meta.app_secret", "meta.page_access_token", "meta.webhook_verify_token")]
    updated = [item.updated_at for item in tracked if item is not None and item.updated_at is not None]
    app_id = setting_value(db, "meta.app_id")
    page_id = setting_value(db, "meta.page_id")
    return MetaIntegrationStatus(
        configured=bool(app_id and page_id and present("meta.page_access_token") and setting_value(db, "meta.graph_api_version")),
        connected=setting_value(db, "meta.connected") == "true",
        app_id=app_id,
        page_id=page_id,
        page_name=setting_value(db, "meta.page_name"),
        webhook_callback_url=setting_value(db, "meta.webhook_callback_url"),
        graph_api_version=setting_value(db, "meta.graph_api_version"),
        app_secret_configured=present("meta.app_secret"),
        page_access_token_configured=present("meta.page_access_token"),
        webhook_verify_token_configured=present("meta.webhook_verify_token"),
        updated_at=max(updated) if updated else None,
    )


def get_campaign_for_user(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id or campaign.tenant_id != user.tenant_id:
            raise HTTPException(status_code=403, detail="Campaign belongs to another portal")
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this campaign")
    return campaign


@app.get("/health")
def health():
    return {"status": "ok", "service": "meloli-api", "version": "1.0.0"}


@app.post("/api/v1/auth/register", response_model=AuthToken, status_code=201)
def register(payload: UserRegister, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account already exists for this email")
    tenant = None
    if payload.tenant_slug:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == payload.tenant_slug.lower(), Tenant.active.is_(True)))
        if not tenant:
            raise HTTPException(status_code=400, detail="Advertising portal is unavailable")
    else:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "meloli-airwaves", Tenant.active.is_(True)))

    partner = None
    if payload.referral_code:
        code = payload.referral_code.strip().upper()
        partner = db.scalar(select(ReferralPartner).where(ReferralPartner.code == code, ReferralPartner.active.is_(True)))
        if not partner:
            raise HTTPException(status_code=400, detail="Referral code is invalid or inactive")
    user = User(tenant_id=tenant.id if tenant else None, full_name=payload.full_name, business_name=payload.business_name, email=email, phone=payload.phone, password_hash=hash_password(payload.password), role=UserRole.ADVERTISER)
    db.add(user)
    db.flush()
    audit(db, user, "account.registered", "user", user.id)
    if partner:
        db.add(ReferralAttribution(partner_id=partner.id, user_id=user.id))
        audit(db, user, "referral.attributed", "referral_partner", partner.id, partner.code)
    session_key = secrets.token_urlsafe(24)
    db.add(AuthSession(user_id=user.id, session_key=session_key, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None))
    db.commit()
    db.refresh(user)
    return AuthToken(access_token=create_access_token(user.id, user.role.value, user.auth_version or 0, session_key), user=user)


@app.post("/api/v1/auth/login", response_model=AuthToken)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    if user.two_factor_enabled:
        if not user.totp_secret:
            raise HTTPException(status_code=409, detail="Two-factor authentication is misconfigured")
        if not payload.otp_code:
            raise HTTPException(status_code=401, detail="Two-factor authentication code required")
        secret = decrypt_secret(user.totp_secret)
        if not pyotp.TOTP(secret).verify(payload.otp_code, valid_window=1):
            raise HTTPException(status_code=401, detail="Invalid two-factor authentication code")
    session_key = secrets.token_urlsafe(24)
    db.add(AuthSession(user_id=user.id, session_key=session_key, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None))
    db.commit()
    return AuthToken(access_token=create_access_token(user.id, user.role.value, user.auth_version or 0, session_key), user=user)


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/v1/packages", response_model=list[PackageOut])
def list_packages(tenant_slug: str | None = None, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    tenant_id = user.tenant_id if user else None
    if tenant_id is None and tenant_slug:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug.lower(), Tenant.active.is_(True)))
        if not tenant:
            raise HTTPException(status_code=404, detail="Advertising portal not found")
        tenant_id = tenant.id
    if tenant_id is None:
        default_tenant = db.scalar(select(Tenant).where(Tenant.slug == "meloli-airwaves", Tenant.active.is_(True)))
        tenant_id = default_tenant.id if default_tenant else None
    query = select(AdvertisingPackage).where(AdvertisingPackage.active.is_(True))
    query = query.where(AdvertisingPackage.tenant_id == tenant_id) if tenant_id is not None else query.where(AdvertisingPackage.tenant_id.is_(None))
    return list(db.scalars(query.order_by(AdvertisingPackage.price)))


@app.get("/api/v1/admin/packages", response_model=list[PackageOut])
def list_admin_packages(admin: User = Depends(package_admin), db: Session = Depends(get_db)):
    query = select(AdvertisingPackage)
    if admin.tenant_id is not None:
        query = query.where(AdvertisingPackage.tenant_id == admin.tenant_id)
    else:
        query = query.where(AdvertisingPackage.tenant_id.is_(None))
    return list(db.scalars(query.order_by(AdvertisingPackage.active.desc(), AdvertisingPackage.price)))


@app.post("/api/v1/admin/packages", response_model=PackageOut, status_code=201)
def create_package(payload: PackageWrite, admin: User = Depends(package_admin), db: Session = Depends(get_db)):
    code = payload.code.upper().strip()
    tenant_filter = AdvertisingPackage.tenant_id == admin.tenant_id if admin.tenant_id is not None else AdvertisingPackage.tenant_id.is_(None)
    if db.scalar(select(AdvertisingPackage).where(tenant_filter, AdvertisingPackage.code == code)):
        raise HTTPException(status_code=409, detail="Package code already exists in this portal")
    package = AdvertisingPackage(tenant_id=admin.tenant_id, code=code, name=payload.name, description=payload.description, price=payload.price, currency=payload.currency.upper(), posts_included=payload.posts_included, max_media_items=payload.max_media_items, allow_video=payload.allow_video, allow_carousel=payload.allow_carousel, active=payload.active)
    db.add(package)
    db.flush()
    audit(db, admin, "package.created", "advertising_package", package.id, code)
    db.commit()
    db.refresh(package)
    return package


@app.put("/api/v1/admin/packages/{package_id}", response_model=PackageOut)
def update_package(package_id: int, payload: PackageWrite, admin: User = Depends(package_admin), db: Session = Depends(get_db)):
    package = db.get(AdvertisingPackage, package_id)
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    if package.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=403, detail="Package belongs to another portal")
    code = payload.code.upper().strip()
    tenant_filter = AdvertisingPackage.tenant_id == admin.tenant_id if admin.tenant_id is not None else AdvertisingPackage.tenant_id.is_(None)
    duplicate = db.scalar(select(AdvertisingPackage).where(tenant_filter, AdvertisingPackage.code == code, AdvertisingPackage.id != package_id))
    if duplicate:
        raise HTTPException(status_code=409, detail="Package code already exists")
    package.code = code
    package.name = payload.name
    package.description = payload.description
    package.price = payload.price
    package.currency = payload.currency.upper()
    package.posts_included = payload.posts_included
    package.max_media_items = payload.max_media_items
    package.allow_video = payload.allow_video
    package.allow_carousel = payload.allow_carousel
    package.active = payload.active
    audit(db, admin, "package.updated", "advertising_package", package.id, code)
    db.commit()
    db.refresh(package)
    return package


@app.get("/api/v1/campaigns", response_model=list[CampaignOut])
def list_campaigns(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Campaign).order_by(Campaign.created_at.desc())
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin:
        query = query.where(Campaign.advertiser_id == user.id)
    elif user.tenant_id:
        query = query.where(Campaign.tenant_id == user.tenant_id)
    return list(db.scalars(query))


@app.post("/api/v1/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.tenant_id:
        subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == user.tenant_id))
        plan = db.get(TenantPlan, subscription.plan_id) if subscription else None
        if not subscription or not plan:
            raise HTTPException(status_code=402, detail="This Page portal does not have a tenant subscription")
        period_end = subscription.current_period_end
        period_end = period_end.replace(tzinfo=timezone.utc) if period_end.tzinfo is None else period_end
        if subscription.status not in {"trialing", "active"} or period_end < datetime.now(timezone.utc):
            raise HTTPException(status_code=402, detail="This Page portal subscription is inactive or expired")
        now = datetime.now(timezone.utc)
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        campaign_count = db.scalar(
            select(func.count(Campaign.id)).where(
                Campaign.tenant_id == user.tenant_id,
                Campaign.created_at >= month_start,
            )
        ) or 0
        if campaign_count >= plan.max_campaigns_monthly:
            raise HTTPException(
                status_code=409,
                detail=f"Your {plan.name} tenant plan monthly campaign limit ({plan.max_campaigns_monthly}) has been reached",
            )
    tenant_filter = AdvertisingPackage.tenant_id == user.tenant_id if user.tenant_id is not None else AdvertisingPackage.tenant_id.is_(None)
    package = db.scalar(select(AdvertisingPackage).where(tenant_filter, AdvertisingPackage.code == payload.package_code.upper(), AdvertisingPackage.active.is_(True)))
    if not package:
        raise HTTPException(status_code=400, detail="Advertising package is unavailable")

    media_items = list(payload.media_items or [])
    if len(media_items) > 10:
        raise HTTPException(status_code=400, detail="A campaign can contain at most 10 media items")
    if len(media_items) > int(package.max_media_items or 10):
        raise HTTPException(status_code=400, detail=f"{package.name} allows at most {package.max_media_items} media item(s)")
    if any(item.content_type.lower().startswith("video/") for item in media_items) and not package.allow_video:
        raise HTTPException(status_code=400, detail=f"{package.name} does not allow video adverts")
    if len(media_items) > 1 and not package.allow_carousel:
        raise HTTPException(status_code=400, detail=f"{package.name} does not allow carousel adverts")
    if len(media_items) > 1 and any(not item.content_type.lower().startswith("image/") for item in media_items):
        raise HTTPException(status_code=400, detail="Carousel campaigns support images only. Use a single video for video adverts")
    if len(media_items) == 1 and not (
        media_items[0].content_type.lower().startswith("image/")
        or media_items[0].content_type.lower().startswith("video/")
    ):
        raise HTTPException(status_code=400, detail="Campaign media must be an image or video")

    primary_media = media_items[0].url if media_items else payload.media_url
    campaign = Campaign(
        tenant_id=user.tenant_id,
        advertiser_id=user.id,
        package_id=package.id,
        title=payload.title,
        engagement_mode=payload.engagement_mode,
        caption=payload.caption,
        media_url=primary_media,
        destination_url=payload.destination_url,
        preferred_publish_at=payload.preferred_publish_at,
        status=CampaignStatus.PAYMENT_PENDING,
    )
    db.add(campaign)
    db.flush()
    for position, item in enumerate(media_items):
        db.add(CampaignMedia(campaign_id=campaign.id, url=item.url, content_type=item.content_type.lower(), position=position))
    audit(db, user, "campaign.created", "campaign", campaign.id, f"Package {package.code}; media {len(media_items) or (1 if primary_media else 0)}")
    if campaign.tenant_id:
        emit_realtime_event(
            db, "campaign.created", tenant_id=campaign.tenant_id, audience="tenant_staff",
            entity_type="campaign", entity_id=campaign.id,
            payload={"campaign_id": campaign.id, "title": campaign.title, "status": campaign.status.value, "advertiser_id": campaign.advertiser_id},
        )
    db.commit()
    db.refresh(campaign)
    return campaign


@app.patch("/api/v1/campaigns/{campaign_id}/decision", response_model=CampaignOut)
def decide_campaign(campaign_id: int, payload: CampaignDecision, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    campaign = get_campaign_for_user(db, campaign_id, staff)
    if campaign.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Cancelled campaigns cannot enter editorial review")
    allowed = {CampaignStatus.IN_REVIEW, CampaignStatus.CHANGES_REQUESTED, CampaignStatus.APPROVED, CampaignStatus.SCHEDULED, CampaignStatus.REJECTED}
    if payload.status not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported editorial decision")
    if campaign.status == CampaignStatus.PAYMENT_PENDING:
        raise HTTPException(status_code=409, detail="Payment must be confirmed before editorial review")
    if payload.status == CampaignStatus.CHANGES_REQUESTED and not payload.reviewer_note:
        raise HTTPException(status_code=400, detail="A change request must include a reviewer note")
    if payload.status == CampaignStatus.APPROVED:
        checklist = db.scalar(select(CampaignReviewChecklist).where(CampaignReviewChecklist.campaign_id == campaign.id))
        if not checklist or not all([
            checklist.content_accuracy_checked,
            checklist.media_rights_checked,
            checklist.contact_details_checked,
            checklist.policy_checked,
        ]):
            raise HTTPException(status_code=409, detail="Complete the moderation checklist before approving this campaign")
    campaign.status = payload.status
    campaign.reviewer_note = payload.reviewer_note
    if payload.status == CampaignStatus.APPROVED:
        campaign.proof_status = "pending_advertiser"
        campaign.proof_requested_at = datetime.now(timezone.utc)
        campaign.proof_approved_at = None
        campaign.proof_feedback = None
        campaign.proof_requested_by_user_id = staff.id
        campaign.proof_approved_by_user_id = None
        notify(db, campaign.advertiser_id, "final_proof", "Final advert proof ready", f"{campaign.title} has passed Meloli editorial review. Please review and approve the final proof before publishing.")
    elif payload.status in {CampaignStatus.CHANGES_REQUESTED, CampaignStatus.REJECTED}:
        campaign.proof_status = "not_requested"
        campaign.proof_approved_at = None
        campaign.proof_approved_by_user_id = None
    if payload.status == CampaignStatus.SCHEDULED:
        if campaign.proof_status != "approved":
            raise HTTPException(status_code=409, detail="Advertiser final-proof approval is required before scheduling")

        if not payload.scheduled_publish_at:
            raise HTTPException(status_code=400, detail="Scheduled campaigns require a publishing date")
        campaign.scheduled_publish_at = payload.scheduled_publish_at
    notify(db, campaign.advertiser_id, "campaign_status", f"Campaign {payload.status.value.replace('_', ' ')}", payload.reviewer_note or f"{campaign.title} is now {payload.status.value.replace('_', ' ')}.")
    audit(db, staff, f"campaign.{payload.status.value}", "campaign", campaign.id, payload.reviewer_note)
    if campaign.tenant_id:
        emit_realtime_event(
            db, "campaign.status_changed", tenant_id=campaign.tenant_id, audience="tenant_staff",
            entity_type="campaign", entity_id=campaign.id,
            payload={"campaign_id": campaign.id, "title": campaign.title, "status": payload.status.value, "reviewer_note": payload.reviewer_note},
        )
    db.commit()
    db.refresh(campaign)
    from .corporate_api import emit_corporate_webhook
    emit_corporate_webhook(db, campaign, f"campaign.{payload.status.value}")
    return campaign


@app.get("/api/v1/campaigns/{campaign_id}/payments", response_model=list[PaymentOut])
def list_payments(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = get_campaign_for_user(db, campaign_id, user)
    return list(db.scalars(select(Payment).where(Payment.campaign_id == campaign.id).order_by(Payment.created_at.desc())))


@app.post("/api/v1/campaigns/{campaign_id}/payments", response_model=PaymentOut, status_code=201)
def create_payment(campaign_id: int, payload: PaymentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = get_campaign_for_user(db, campaign_id, user)
    if campaign.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Cancelled campaigns cannot accept payments")
    package = db.get(AdvertisingPackage, campaign.package_id)
    if not package:
        raise HTTPException(status_code=409, detail="Campaign package no longer exists")

    promo = promo_for_code(db, payload.promo_code)
    amount = discounted_amount(package.price, promo)
    payment_status = PaymentStatus.PENDING
    paid_at = None
    method = payload.method

    if method == "corporate_credit":
        account = db.scalar(select(CorporateAccount).where(CorporateAccount.user_id == campaign.advertiser_id))
        if not account or not account.active:
            raise HTTPException(status_code=409, detail="Corporate credit is not enabled for this advertiser")
        available = float(account.credit_limit) - float(account.credit_used)
        if float(amount) > available:
            raise HTTPException(status_code=409, detail=f"Corporate credit available is LSL {available:,.2f}")
        account.credit_used = float(account.credit_used) + float(amount)
        payment_status = PaymentStatus.PAID
        paid_at = datetime.now(timezone.utc)
    elif method == "subscription":
        subscription = db.scalar(
            select(AdvertiserSubscription)
            .where(
                AdvertiserSubscription.user_id == campaign.advertiser_id,
                AdvertiserSubscription.active.is_(True),
                AdvertiserSubscription.period_end >= datetime.now(timezone.utc),
                AdvertiserSubscription.remaining_posts > 0,
            )
            .order_by(AdvertiserSubscription.period_end.desc())
        )
        if not subscription:
            raise HTTPException(status_code=409, detail="No active monthly plan with remaining adverts is available")
        subscription.remaining_posts -= 1
        amount = discounted_amount(0, None)
        payment_status = PaymentStatus.PAID
        paid_at = datetime.now(timezone.utc)

    payment = Payment(
        campaign_id=campaign.id,
        amount=amount,
        currency=package.currency,
        method=method,
        reference=payload.reference or (payload.promo_code.strip().upper() if payload.promo_code else None),
        promo_code_id=promo.id if promo else None,
        status=payment_status,
        paid_at=paid_at,
    )
    db.add(payment)
    db.flush()

    if promo:
        promo.uses += 1
    if payment_status == PaymentStatus.PAID and campaign.status == CampaignStatus.PAYMENT_PENDING:
        campaign.status = CampaignStatus.SUBMITTED
        notify(db, campaign.advertiser_id, "payment", "Campaign funded", f"{campaign.title} is funded by {method.replace('_', ' ')} and is ready for editorial review.")

    detail = f"Campaign {campaign.id}; amount {package.currency} {float(amount):.2f}"
    if promo:
        detail += f"; promo {promo.code}"
    audit(db, user, "payment.created", "payment", payment.id, detail)
    if campaign.tenant_id:
        emit_realtime_event(
            db, "payment.created", tenant_id=campaign.tenant_id, audience="tenant_staff",
            entity_type="payment", entity_id=payment.id,
            payload={"payment_id": payment.id, "campaign_id": campaign.id, "status": payment.status.value, "amount": float(payment.amount), "currency": payment.currency},
        )
    db.commit()
    db.refresh(payment)
    return payment


@app.patch("/api/v1/payments/{payment_id}", response_model=PaymentOut)
def decide_payment(payment_id: int, payload: PaymentDecision, staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment.status = payload.status
    if payload.reference is not None:
        payment.reference = payload.reference
    campaign = db.get(Campaign, payment.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    get_campaign_for_user(db, campaign.id, staff)
    if payload.status == PaymentStatus.PAID:
        payment.paid_at = datetime.now(timezone.utc)
        if campaign and campaign.status == CampaignStatus.PAYMENT_PENDING:
            campaign.status = CampaignStatus.SUBMITTED
        if campaign:
            notify(db, campaign.advertiser_id, "payment", "Payment confirmed", f"Payment for {campaign.title} has been confirmed and the advert is ready for review.")
    elif campaign:
        notify(db, campaign.advertiser_id, "payment", f"Payment {payload.status.value}", f"Payment for {campaign.title} is marked {payload.status.value}.")
    audit(db, staff, f"payment.{payload.status.value}", "payment", payment.id, payment.reference)
    if campaign.tenant_id:
        emit_realtime_event(
            db, "payment.status_changed", tenant_id=campaign.tenant_id, audience="tenant_staff",
            entity_type="payment", entity_id=payment.id,
            payload={"payment_id": payment.id, "campaign_id": campaign.id, "status": payload.status.value, "reference": payment.reference},
        )
    db.commit()
    db.refresh(payment)
    return payment


@app.get("/api/v1/payments/{payment_id}/receipt.pdf")
def payment_receipt(payment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    campaign = get_campaign_for_user(db, payment.campaign_id, user)
    if payment.status != PaymentStatus.PAID:
        raise HTTPException(status_code=409, detail="A receipt is available only after payment is confirmed")
    advertiser = db.get(User, campaign.advertiser_id)
    package = db.get(AdvertisingPackage, campaign.package_id)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    brand_name, _, _ = tenant_brand(db, campaign.tenant_id)
    document_no = f"RCT-{payment.id:06d}"
    pdf.setTitle(f"{brand_name} payment receipt {document_no}")
    draw_header(pdf, db, "Payment receipt", document_no, "PAID", tenant_id=campaign.tenant_id)

    top = height - 154
    pdf.setFillColor(LIGHT)
    pdf.roundRect(46, top - 92, width - 92, 92, 14, fill=1, stroke=0)
    info_label(pdf, 62, top - 22, "Received from", advertiser.business_name or advertiser.full_name if advertiser else f"Advertiser {campaign.advertiser_id}")
    info_label(pdf, 62, top - 58, "Email", advertiser.email if advertiser else "—")
    info_label(pdf, 305, top - 22, "Campaign", campaign.title, 42)
    paid_at = payment.paid_at.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC") if payment.paid_at else "—"
    info_label(pdf, 305, top - 58, "Paid at", paid_at, 40)

    y = top - 132
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(46, y, "PAYMENT DETAILS")
    details = [
        ("Package", package.name if package else f"Package {campaign.package_id}"),
        ("Method", payment.method.replace("_", " ").title()),
        ("Reference", payment.reference or "—"),
    ]
    y -= 26
    for label, value in details:
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(46, y, label.upper())
        pdf.setFillColor(NAVY)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(160, y, str(value)[:58])
        y -= 24

    pdf.setFillColor(NAVY)
    pdf.roundRect(46, y - 72, width - 92, 72, 14, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(62, y - 26, "AMOUNT RECEIVED")
    pdf.setFont("Helvetica-Bold", 23)
    pdf.drawRightString(width - 62, y - 31, f"{payment.currency} {float(payment.amount):,.2f}")
    pdf.setFillColor(colors.HexColor("#C7CBDC"))
    pdf.setFont("Helvetica", 8)
    pdf.drawString(62, y - 50, f"Payment verified in the {brand_name} Advertising Portal.")

    note_y = 112
    pdf.setFillColor(colors.HexColor("#ECFDF5"))
    pdf.roundRect(46, note_y, width - 92, 46, 12, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#15803D"))
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(60, note_y + 29, "PAYMENT CONFIRMED")
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(60, note_y + 14, "Thank you. This receipt confirms payment for the advertising campaign shown above.")

    draw_footer(pdf, db, campaign.tenant_id)
    pdf.save()
    data = buffer.getvalue()
    audit(db, user, "receipt.generated", "payment", payment.id)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="advertising-receipt-{payment.id}.pdf"'})


@app.get("/api/v1/notifications", response_model=list[NotificationOut])
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)))


@app.post("/api/v1/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(notification_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(notification)
    return notification


@app.get("/api/v1/admin/reports/summary", response_model=ReportSummary)
def report_summary(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    tenant_id = None if staff.role == UserRole.SUPER_ADMIN else staff.tenant_id
    if staff.role != UserRole.SUPER_ADMIN and tenant_id is None:
        raise HTTPException(status_code=403, detail="Staff account is not attached to a tenant")
    advertiser_query = select(func.count(User.id)).where(User.role == UserRole.ADVERTISER)
    campaign_query = select(func.count(Campaign.id))
    awaiting_query = select(func.count(Campaign.id)).where(Campaign.status.in_([CampaignStatus.SUBMITTED, CampaignStatus.IN_REVIEW]))
    scheduled_query = select(func.count(Campaign.id)).where(Campaign.status == CampaignStatus.SCHEDULED)
    published_query = select(func.count(Campaign.id)).where(Campaign.status == CampaignStatus.PUBLISHED)
    payment_count_query = select(func.count(Payment.id)).join(Campaign, Campaign.id == Payment.campaign_id).where(Payment.status == PaymentStatus.PAID)
    revenue_query = select(func.coalesce(func.sum(Payment.amount), 0)).join(Campaign, Campaign.id == Payment.campaign_id).where(Payment.status == PaymentStatus.PAID)
    failed_query = select(func.count(PublicationAttempt.id)).join(Campaign, Campaign.id == PublicationAttempt.campaign_id).where(PublicationAttempt.status == PublicationStatus.FAILED)
    if tenant_id:
        advertiser_query = advertiser_query.where(User.tenant_id == tenant_id)
        campaign_query = campaign_query.where(Campaign.tenant_id == tenant_id)
        awaiting_query = awaiting_query.where(Campaign.tenant_id == tenant_id)
        scheduled_query = scheduled_query.where(Campaign.tenant_id == tenant_id)
        published_query = published_query.where(Campaign.tenant_id == tenant_id)
        payment_count_query = payment_count_query.where(Campaign.tenant_id == tenant_id)
        revenue_query = revenue_query.where(Campaign.tenant_id == tenant_id)
        failed_query = failed_query.where(Campaign.tenant_id == tenant_id)
    return ReportSummary(
        advertisers=db.scalar(advertiser_query) or 0,
        campaigns=db.scalar(campaign_query) or 0,
        awaiting_review=db.scalar(awaiting_query) or 0,
        scheduled=db.scalar(scheduled_query) or 0,
        published=db.scalar(published_query) or 0,
        paid_payments=db.scalar(payment_count_query) or 0,
        revenue=float(db.scalar(revenue_query) or 0),
        failed_publications=db.scalar(failed_query) or 0,
    )


@app.get("/api/v1/publications", response_model=list[PublicationOut])
def list_publications(staff: User = Depends(staff_user), db: Session = Depends(get_db)):
    query = select(PublicationAttempt).join(Campaign, Campaign.id == PublicationAttempt.campaign_id).order_by(PublicationAttempt.created_at.desc()).limit(200)
    if staff.role != UserRole.SUPER_ADMIN:
        if not staff.tenant_id:
            raise HTTPException(status_code=403, detail="Staff account is not attached to a tenant")
        query = query.where(Campaign.tenant_id == staff.tenant_id)
    return list(db.scalars(query))


@app.post("/api/v1/campaigns/{campaign_id}/publish", response_model=PublishResult)
def publish_campaign(campaign_id: int, publisher: User = Depends(publisher_user), db: Session = Depends(get_db)):
    campaign = get_campaign_for_user(db, campaign_id, publisher)
    if campaign.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Cancelled campaigns cannot be published")
    if campaign.status not in {CampaignStatus.APPROVED, CampaignStatus.SCHEDULED}:
        raise HTTPException(status_code=409, detail="Only approved or scheduled campaigns can be published")
    if campaign.proof_status != "approved":
        raise HTTPException(status_code=409, detail="Advertiser final-proof approval is required before publishing")
    if campaign.facebook_post_id:
        raise HTTPException(status_code=409, detail="Campaign has already been published")

    from .tenancy import tenant_setting
    page_id = tenant_setting(db, campaign.tenant_id, "meta.page_id") if campaign.tenant_id else None
    token = tenant_setting(db, campaign.tenant_id, "meta.page_access_token") if campaign.tenant_id else None
    version = tenant_setting(db, campaign.tenant_id, "meta.graph_api_version") if campaign.tenant_id else None
    page_id = page_id or setting_value(db, "meta.page_id")
    token = token or setting_secret(db, "meta.page_access_token")
    version = version or setting_value(db, "meta.graph_api_version")
    if not page_id or not token or not version:
        raise HTTPException(status_code=409, detail="Meta publishing is not fully configured in System Configuration")

    previous = db.scalar(select(func.count(PublicationAttempt.id)).where(PublicationAttempt.campaign_id == campaign.id)) or 0
    attempt = PublicationAttempt(campaign_id=campaign.id, attempt_number=int(previous) + 1, status=PublicationStatus.PENDING)
    db.add(attempt)
    db.flush()
    try:
        result = publish_to_meta(
            page_id=page_id,
            access_token=token,
            version=version,
            message=campaign.caption,
            media_url=campaign.media_url,
            destination_url=campaign.destination_url,
            media_items=[(item.url, item.content_type) for item in campaign.media_items],
        )
        attempt.status = PublicationStatus.PUBLISHED
        attempt.external_post_id = result.post_id
        attempt.external_post_url = result.post_url
        campaign.facebook_post_id = result.post_id
        campaign.facebook_post_url = result.post_url
        campaign.published_at = datetime.now(timezone.utc)
        campaign.status = CampaignStatus.PUBLISHED
        campaign.publishing_retry_exhausted_at = None
        tenant = db.get(Tenant, campaign.tenant_id) if campaign.tenant_id else None
        portal_name = tenant.name if tenant else "Advertising Portal"
        notify(db, campaign.advertiser_id, "published", "Your advert is live", f"{campaign.title} has been published on the {portal_name} Facebook Page.")
        audit(db, publisher, "campaign.published", "campaign", campaign.id, result.post_id)
        if campaign.tenant_id:
            emit_realtime_event(
                db, "campaign.published", tenant_id=campaign.tenant_id, audience="tenant_staff",
                entity_type="campaign", entity_id=campaign.id,
                payload={"campaign_id": campaign.id, "title": campaign.title, "facebook_post_url": result.post_url},
            )
        db.commit()
        db.refresh(campaign)
        db.refresh(attempt)
        from .corporate_api import emit_corporate_webhook
        emit_corporate_webhook(db, campaign, "campaign.published")
        return PublishResult(campaign=campaign, publication=attempt)
    except MetaError as exc:
        attempt.status = PublicationStatus.FAILED
        attempt.error_message = str(exc)[:4000]
        audit(db, publisher, "campaign.publish_failed", "campaign", campaign.id, str(exc))
        if campaign.tenant_id:
            emit_realtime_event(
                db, "campaign.publish_failed", tenant_id=campaign.tenant_id, audience="tenant_staff",
                entity_type="campaign", entity_id=campaign.id,
                payload={"campaign_id": campaign.id, "title": campaign.title, "error": str(exc)[:500]},
            )
        db.commit()
        from .corporate_api import emit_corporate_webhook
        emit_corporate_webhook(db, campaign, "campaign.publish_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/campaigns/{campaign_id}/publish/retry", response_model=PublishResult)
def retry_publish_campaign(campaign_id: int, publisher: User = Depends(publisher_user), db: Session = Depends(get_db)):
    campaign = get_campaign_for_user(db, campaign_id, publisher)
    campaign.publishing_retry_exhausted_at = None
    db.commit()
    return publish_campaign(campaign_id=campaign_id, publisher=publisher, db=db)


@app.get("/api/v1/system/integrations/meta", response_model=MetaIntegrationStatus)
def get_meta_integration(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    return meta_status(db)


@app.put("/api/v1/system/integrations/meta", response_model=MetaIntegrationStatus)
def update_meta_integration(payload: MetaIntegrationUpdate, admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    set_setting(db, "meta.app_id", payload.app_id)
    set_setting(db, "meta.page_id", payload.page_id)
    set_setting(db, "meta.webhook_callback_url", payload.webhook_callback_url)
    set_setting(db, "meta.graph_api_version", payload.graph_api_version)
    if payload.app_secret is not None:
        set_setting(db, "meta.app_secret", payload.app_secret.get_secret_value(), encrypted=True)
    if payload.page_access_token is not None:
        set_setting(db, "meta.page_access_token", payload.page_access_token.get_secret_value(), encrypted=True)
    if payload.webhook_verify_token is not None:
        set_setting(db, "meta.webhook_verify_token", payload.webhook_verify_token.get_secret_value(), encrypted=True)
    set_setting(db, "meta.connected", "false")
    set_setting(db, "meta.page_name", None)
    audit(db, admin, "meta.configuration.updated", "system_setting", detail="Meta integration configuration changed")
    db.commit()
    return meta_status(db)


@app.post("/api/v1/system/integrations/meta/test", response_model=MetaIntegrationStatus)
def test_meta_integration(admin: User = Depends(super_admin), db: Session = Depends(get_db)):
    page_id = setting_value(db, "meta.page_id")
    token = setting_secret(db, "meta.page_access_token")
    version = setting_value(db, "meta.graph_api_version")
    if not page_id or not token or not version:
        raise HTTPException(status_code=409, detail="Page ID, Page access token and Graph API version are required")
    try:
        page = verify_page(page_id, token, version)
    except MetaError as exc:
        set_setting(db, "meta.connected", "false")
        audit(db, admin, "meta.connection_failed", "system_setting", detail=str(exc))
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    set_setting(db, "meta.connected", "true")
    set_setting(db, "meta.page_name", page.name)
    audit(db, admin, "meta.connection_verified", "system_setting", detail=f"{page.name} ({page.id})")
    db.commit()
    return meta_status(db)
