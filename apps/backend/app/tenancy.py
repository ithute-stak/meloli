import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import dns.resolver
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AdvertisingPackage, AuditLog, Campaign, Tenant, TenantDomain, TenantPlan, TenantSetting, TenantSubscription, User, UserRole
from .security import decode_access_token, encrypt_secret, hash_password, validate_token_user

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class TenantRegister(BaseModel):
    page_name: str = Field(min_length=2, max_length=180)
    facebook_page_id: str | None = Field(default=None, max_length=120)
    desired_slug: str | None = Field(default=None, max_length=80)
    owner_name: str = Field(min_length=2, max_length=160)
    owner_email: EmailStr
    owner_phone: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=10, max_length=128)


class TenantProfileWrite(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    facebook_page_name: str | None = Field(default=None, max_length=180)
    facebook_page_id: str | None = Field(default=None, max_length=120)
    logo_url: str | None = Field(default=None, max_length=1000)
    accent_color: str = Field(default="#e31545", pattern=r"^#[0-9A-Fa-f]{6}$")
    email_sender_name: str | None = Field(default=None, max_length=180)
    support_email: EmailStr | None = None
    support_phone: str | None = Field(default=None, max_length=60)
    document_footer: str | None = Field(default=None, max_length=240)


class DomainWrite(BaseModel):
    hostname: str = Field(min_length=4, max_length=255)


class TenantStateWrite(BaseModel):
    active: bool


class TenantPlanWrite(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)
    monthly_price: float = Field(ge=0)
    annual_price: float = Field(ge=0)
    currency: str = Field(default="LSL", min_length=3, max_length=8)
    max_staff: int = Field(default=2, ge=1, le=500)
    max_campaigns_monthly: int = Field(default=50, ge=1, le=100000)
    custom_domains: bool = False
    competition_certification: bool = False
    active: bool = True


class TenantSubscriptionWrite(BaseModel):
    plan_id: int
    billing_period: str = Field(default="monthly", pattern=r"^(monthly|annual)$")
    status: str = Field(default="active", pattern=r"^(trialing|active|past_due|suspended|cancelled)$")


class TenantStaffCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: UserRole


class TenantStaffState(BaseModel):
    active: bool


class TenantMetaWrite(BaseModel):
    app_id: str | None = Field(default=None, max_length=200)
    app_secret: SecretStr | None = None
    page_id: str | None = Field(default=None, max_length=200)
    page_access_token: SecretStr | None = None
    webhook_verify_token: SecretStr | None = None
    graph_api_version: str = Field(default="v24.0", max_length=32)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def tenant_admin(user: User = Depends(current_user)) -> User:
    if not user.is_tenant_admin and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Tenant administrator access required")
    if not user.tenant_id:
        raise HTTPException(status_code=409, detail="This account is not attached to a tenant")
    return user


def platform_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Platform super admin access required")
    return user


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "page"


def clean_hostname(value: str) -> str:
    host = value.strip().lower()
    host = re.sub(r"^https?://", "", host).split("/", 1)[0].split(":", 1)[0].strip(".")
    if not host or "." not in host or " " in host:
        raise HTTPException(status_code=400, detail="Enter a valid custom hostname, for example ads.example.com")
    return host


def ensure_facebook_page_available(db: Session, page_id: str | None, tenant_id: int | None = None) -> str | None:
    normalized = page_id.strip() if page_id else None
    if not normalized:
        return None
    query = select(Tenant.id).where(Tenant.facebook_page_id == normalized)
    if tenant_id is not None:
        query = query.where(Tenant.id != tenant_id)
    if db.scalar(query):
        raise HTTPException(status_code=409, detail="This Facebook Page is already registered to another portal")
    return normalized


def tenant_setting(db: Session, tenant_id: int, key: str) -> str | None:
    row = db.scalar(select(TenantSetting).where(TenantSetting.tenant_id == tenant_id, TenantSetting.key == key).order_by(TenantSetting.id.desc()))
    if not row or not row.value:
        return None
    if row.encrypted:
        from .security import decrypt_secret
        return decrypt_secret(row.value)
    return row.value


def set_tenant_setting(db: Session, tenant_id: int, key: str, value: str | None, encrypted: bool = False) -> None:
    row = db.scalar(select(TenantSetting).where(TenantSetting.tenant_id == tenant_id, TenantSetting.key == key).order_by(TenantSetting.id.desc()))
    stored = encrypt_secret(value) if encrypted and value else value
    if row:
        row.value = stored
        row.encrypted = encrypted
    else:
        db.add(TenantSetting(tenant_id=tenant_id, key=key, value=stored, encrypted=encrypted))


def current_tenant_subscription(db: Session, tenant_id: int) -> tuple[TenantSubscription | None, TenantPlan | None]:
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant_id))
    plan = db.get(TenantPlan, subscription.plan_id) if subscription else None
    return subscription, plan


def subscription_payload(subscription: TenantSubscription | None, plan: TenantPlan | None) -> dict | None:
    if not subscription or not plan:
        return None
    now = datetime.now(timezone.utc)
    period_end = subscription.current_period_end
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    return {
        "id": subscription.id,
        "status": subscription.status,
        "billing_period": subscription.billing_period,
        "price_amount": float(subscription.price_amount),
        "currency": subscription.currency,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "trial_ends_at": subscription.trial_ends_at,
        "usable": subscription.status in {"trialing", "active"} and period_end >= now,
        "plan": {
            "id": plan.id,
            "code": plan.code,
            "name": plan.name,
            "max_staff": plan.max_staff,
            "max_campaigns_monthly": plan.max_campaigns_monthly,
            "custom_domains": plan.custom_domains,
            "competition_certification": plan.competition_certification,
        },
    }


def onboarding_payload(db: Session, tenant: Tenant) -> dict:
    subscription, plan = current_tenant_subscription(db, tenant.id)
    staff_count = db.scalar(
        select(func.count(User.id)).where(
            User.tenant_id == tenant.id,
            User.is_tenant_admin.is_(False),
            User.role.in_([UserRole.REVIEWER, UserRole.PUBLISHER]),
        )
    ) or 0
    package_count = db.scalar(select(func.count(AdvertisingPackage.id)).where(AdvertisingPackage.tenant_id == tenant.id)) or 0
    custom_domain = bool(db.scalar(select(TenantDomain.id).where(TenantDomain.tenant_id == tenant.id, TenantDomain.status == "verified")))
    steps = [
        {"key": "identity", "label": "Portal identity", "complete": bool(tenant.name and tenant.slug)},
        {"key": "facebook_page", "label": "Facebook Page identity", "complete": bool(tenant.facebook_page_id)},
        {"key": "meta", "label": "Meta connection", "complete": tenant_setting(db, tenant.id, "meta.connected") == "true"},
        {"key": "packages", "label": "Advertising packages", "complete": package_count > 0},
        {"key": "staff", "label": "Team setup", "complete": staff_count > 0},
    ]
    if plan and plan.custom_domains:
        steps.append({"key": "domain", "label": "Custom domain", "complete": custom_domain})
    completed = sum(1 for step in steps if step["complete"])
    return {
        "percent": round((completed / len(steps)) * 100) if steps else 100,
        "completed": completed,
        "total": len(steps),
        "steps": steps,
        "subscription": subscription_payload(subscription, plan),
    }


def tenant_payload(tenant: Tenant) -> dict:
    base = os.getenv("FRONTEND_PUBLIC_URL", "http://localhost:3000").rstrip("/")
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "facebook_page_name": tenant.facebook_page_name,
        "facebook_page_id": tenant.facebook_page_id,
        "logo_url": tenant.logo_url,
        "accent_color": tenant.accent_color,
        "active": tenant.active,
        "generated_url": f"{base}/p/{tenant.slug}",
    }


@router.post("/api/v1/tenants/register", status_code=201)
def register_tenant(payload: TenantRegister, db: Session = Depends(get_db)):
    email = str(payload.owner_email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    facebook_page_id = ensure_facebook_page_available(db, payload.facebook_page_id)

    base_slug = slugify(payload.desired_slug or payload.page_name)
    slug = base_slug
    counter = 2
    while db.scalar(select(Tenant.id).where(Tenant.slug == slug)):
        slug = f"{base_slug[:72]}-{counter}"
        counter += 1

    tenant = Tenant(
        name=payload.page_name.strip(),
        slug=slug,
        facebook_page_name=payload.page_name.strip(),
        facebook_page_id=facebook_page_id,
        accent_color="#e31545",
        active=True,
    )
    db.add(tenant)
    db.flush()
    owner = User(
        tenant_id=tenant.id,
        is_tenant_admin=True,
        full_name=payload.owner_name.strip(),
        business_name=payload.page_name.strip(),
        email=email,
        phone=payload.owner_phone,
        password_hash=hash_password(payload.password),
        role=UserRole.ADVERTISER,
        is_active=True,
    )
    db.add(owner)
    db.flush()

    default_tenant = db.scalar(select(Tenant).where(Tenant.slug == "meloli-airwaves"))
    package_query = select(AdvertisingPackage).where(AdvertisingPackage.active.is_(True))
    if default_tenant:
        package_query = package_query.where(AdvertisingPackage.tenant_id == default_tenant.id)
    else:
        package_query = package_query.where(AdvertisingPackage.tenant_id.is_(None))
    for template in db.scalars(package_query.order_by(AdvertisingPackage.id)):
        db.add(
            AdvertisingPackage(
                tenant_id=tenant.id,
                code=template.code,
                name=template.name,
                description=template.description,
                price=template.price,
                currency=template.currency,
                posts_included=template.posts_included,
                max_media_items=template.max_media_items,
                allow_video=template.allow_video,
                allow_carousel=template.allow_carousel,
                active=template.active,
            )
        )

    starter_plan = db.scalar(select(TenantPlan).where(TenantPlan.code == "STARTER", TenantPlan.active.is_(True)))
    if starter_plan:
        now = datetime.now(timezone.utc)
        db.add(TenantSubscription(
            tenant_id=tenant.id,
            plan_id=starter_plan.id,
            status="trialing",
            billing_period="monthly",
            price_amount=starter_plan.monthly_price,
            currency=starter_plan.currency,
            current_period_start=now,
            current_period_end=now + timedelta(days=14),
            trial_ends_at=now + timedelta(days=14),
        ))

    db.add(AuditLog(actor_user_id=owner.id, action="tenant.registered", entity_type="tenant", entity_id=str(tenant.id), detail=tenant.slug))
    db.commit()
    return {**tenant_payload(tenant), "owner_user_id": owner.id}


@router.get("/api/v1/tenants/resolve")
def resolve_tenant(slug: str | None = None, host: str | None = None, db: Session = Depends(get_db)):
    tenant = None
    if slug:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == slug.lower(), Tenant.active.is_(True)))
    elif host:
        hostname = clean_hostname(host)
        domain = db.scalar(select(TenantDomain).where(TenantDomain.hostname == hostname, TenantDomain.status == "verified"))
        tenant = db.get(Tenant, domain.tenant_id) if domain else None
    if not tenant or not tenant.active:
        raise HTTPException(status_code=404, detail="Portal not found")
    domains = list(db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == tenant.id, TenantDomain.status == "verified")))
    return {**tenant_payload(tenant), "custom_domains": [row.hostname for row in domains]}


@router.get("/api/v1/admin/tenants")
def list_tenants(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Tenant).order_by(Tenant.created_at.desc())))
    result = []
    for tenant in rows:
        domains = list(db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == tenant.id).order_by(TenantDomain.created_at)))
        subscription, plan = current_tenant_subscription(db, tenant.id)
        onboarding = onboarding_payload(db, tenant)
        result.append({
            **tenant_payload(tenant),
            "owner": next((
                {"id": user.id, "name": user.full_name, "email": user.email}
                for user in db.scalars(select(User).where(User.tenant_id == tenant.id, User.is_tenant_admin.is_(True)).order_by(User.id))
            ), None),
            "users": db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id)) or 0,
            "campaigns": db.scalar(select(func.count(Campaign.id)).where(Campaign.tenant_id == tenant.id)) or 0,
            "domains": [{"id": d.id, "hostname": d.hostname, "status": d.status, "verified_at": d.verified_at} for d in domains],
            "subscription": subscription_payload(subscription, plan),
            "onboarding_percent": onboarding["percent"],
        })
    return result


@router.patch("/api/v1/admin/tenants/{tenant_id}/state")
def set_tenant_state(tenant_id: int, payload: TenantStateWrite, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.active = payload.active
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.enabled" if payload.active else "tenant.disabled", entity_type="tenant", entity_id=str(tenant.id), detail=tenant.slug))
    db.commit()
    return {"id": tenant.id, "active": tenant.active}


@router.get("/api/v1/tenant-admin/profile")
def tenant_admin_profile(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, admin.tenant_id)
    domains = list(db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == admin.tenant_id).order_by(TenantDomain.created_at.desc())))
    return {
        **tenant_payload(tenant),
        "email_sender_name": tenant_setting(db, tenant.id, "branding.email_sender_name") or tenant.name,
        "support_email": tenant_setting(db, tenant.id, "branding.support_email"),
        "support_phone": tenant_setting(db, tenant.id, "branding.support_phone"),
        "document_footer": tenant_setting(db, tenant.id, "branding.document_footer"),
        "portal_cname_target": os.getenv("PORTAL_CNAME_TARGET", "portal.example.com"),
        "domains": [{
            "id": row.id,
            "hostname": row.hostname,
            "status": row.status,
            "verification_token": row.verification_token,
            "verified_at": row.verified_at,
        } for row in domains],
    }


@router.put("/api/v1/tenant-admin/profile")
def update_tenant_profile(payload: TenantProfileWrite, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, admin.tenant_id)
    facebook_page_id = ensure_facebook_page_available(db, payload.facebook_page_id, tenant.id)
    tenant.name = payload.name.strip()
    tenant.facebook_page_name = payload.facebook_page_name.strip() if payload.facebook_page_name else None
    tenant.facebook_page_id = facebook_page_id
    tenant.logo_url = payload.logo_url
    tenant.accent_color = payload.accent_color
    set_tenant_setting(db, tenant.id, "branding.email_sender_name", payload.email_sender_name.strip() if payload.email_sender_name else None)
    set_tenant_setting(db, tenant.id, "branding.support_email", str(payload.support_email) if payload.support_email else None)
    set_tenant_setting(db, tenant.id, "branding.support_phone", payload.support_phone.strip() if payload.support_phone else None)
    set_tenant_setting(db, tenant.id, "branding.document_footer", payload.document_footer.strip() if payload.document_footer else None)
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.profile_updated", entity_type="tenant", entity_id=str(tenant.id), detail=tenant.slug))
    db.commit()
    return {
        **tenant_payload(tenant),
        "email_sender_name": tenant_setting(db, tenant.id, "branding.email_sender_name") or tenant.name,
        "support_email": tenant_setting(db, tenant.id, "branding.support_email"),
        "support_phone": tenant_setting(db, tenant.id, "branding.support_phone"),
        "document_footer": tenant_setting(db, tenant.id, "branding.document_footer"),
    }


@router.post("/api/v1/tenant-admin/domains", status_code=201)
def add_custom_domain(payload: DomainWrite, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    subscription, plan = current_tenant_subscription(db, admin.tenant_id)
    details = subscription_payload(subscription, plan)
    if not details or not details["usable"]:
        raise HTTPException(status_code=402, detail="An active tenant subscription is required for custom domains")
    if not plan or not plan.custom_domains:
        raise HTTPException(status_code=403, detail="Your current tenant plan does not include custom domains")
    hostname = clean_hostname(payload.hostname)
    existing = db.scalar(select(TenantDomain).where(TenantDomain.hostname == hostname))
    if existing:
        raise HTTPException(status_code=409, detail="This hostname is already registered")
    row = TenantDomain(
        tenant_id=admin.tenant_id,
        hostname=hostname,
        verification_token="meloli-" + secrets.token_urlsafe(24),
        status="pending",
    )
    db.add(row)
    db.flush()
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.domain_requested", entity_type="tenant_domain", entity_id=str(row.id), detail=hostname))
    db.commit()
    portal_host = os.getenv("PORTAL_CNAME_TARGET", "portal.example.com")
    return {
        "id": row.id,
        "hostname": row.hostname,
        "status": row.status,
        "verification_token": row.verification_token,
        "dns": {
            "cname_name": row.hostname,
            "cname_target": portal_host,
            "txt_name": f"_meloli-verify.{row.hostname}",
            "txt_value": row.verification_token,
        },
    }


@router.post("/api/v1/tenant-admin/domains/{domain_id}/verify")
def verify_own_custom_domain(domain_id: int, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    row = db.get(TenantDomain, domain_id)
    if not row or row.tenant_id != admin.tenant_id:
        raise HTTPException(status_code=404, detail="Custom domain not found")
    txt_name = f"_meloli-verify.{row.hostname}"
    expected = row.verification_token
    try:
        answers = dns.resolver.resolve(txt_name, "TXT")
        values = []
        for answer in answers:
            text_value = b"".join(getattr(answer, "strings", [])).decode("utf-8") if getattr(answer, "strings", None) else str(answer).strip('"')
            values.append(text_value)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Verification TXT record not found yet: {str(exc)[:180]}") from exc
    if expected not in values:
        raise HTTPException(status_code=409, detail="Verification TXT record exists but does not contain the expected token")

    portal_host = os.getenv("PORTAL_CNAME_TARGET", "portal.example.com").strip().lower().rstrip(".")
    try:
        cname_answers = dns.resolver.resolve(row.hostname, "CNAME")
        cname_targets = {str(answer.target).strip().lower().rstrip(".") for answer in cname_answers}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Portal CNAME record not found yet: {str(exc)[:180]}") from exc
    if portal_host not in cname_targets:
        raise HTTPException(
            status_code=409,
            detail=f"Domain ownership is proven, but the CNAME must point to {portal_host} before routing can be activated",
        )

    row.status = "verified"
    row.verified_at = datetime.now(timezone.utc)
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.domain_verified_dns", entity_type="tenant_domain", entity_id=str(row.id), detail=row.hostname))
    db.commit()
    return {
        "id": row.id,
        "hostname": row.hostname,
        "status": row.status,
        "verified_at": row.verified_at,
        "routing_note": "Ownership is verified. Keep the domain pointed at the platform CNAME target for portal routing.",
    }


@router.post("/api/v1/admin/tenant-domains/{domain_id}/verify")
def verify_custom_domain(domain_id: int, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    row = db.get(TenantDomain, domain_id)
    if not row:
        raise HTTPException(status_code=404, detail="Custom domain not found")
    row.status = "verified"
    row.verified_at = datetime.now(timezone.utc)
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.domain_verified", entity_type="tenant_domain", entity_id=str(row.id), detail=row.hostname))
    db.commit()
    return {"id": row.id, "hostname": row.hostname, "status": row.status, "verified_at": row.verified_at}


@router.get("/api/v1/admin/tenant-plans")
def list_tenant_plans(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(TenantPlan).order_by(TenantPlan.monthly_price, TenantPlan.id)))
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
        "active": row.active,
    } for row in rows]


@router.post("/api/v1/admin/tenant-plans", status_code=201)
def create_tenant_plan(payload: TenantPlanWrite, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    code = payload.code.strip().upper()
    if db.scalar(select(TenantPlan.id).where(TenantPlan.code == code)):
        raise HTTPException(status_code=409, detail="Tenant plan code already exists")
    plan = TenantPlan(
        code=code,
        name=payload.name.strip(),
        description=payload.description,
        monthly_price=payload.monthly_price,
        annual_price=payload.annual_price,
        currency=payload.currency.upper(),
        max_staff=payload.max_staff,
        max_campaigns_monthly=payload.max_campaigns_monthly,
        custom_domains=payload.custom_domains,
        competition_certification=payload.competition_certification,
        active=payload.active,
    )
    db.add(plan)
    db.flush()
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.plan_created", entity_type="tenant_plan", entity_id=str(plan.id), detail=plan.code))
    db.commit()
    return {"id": plan.id, "code": plan.code, "name": plan.name}


@router.put("/api/v1/admin/tenants/{tenant_id}/subscription")
def set_tenant_subscription(tenant_id: int, payload: TenantSubscriptionWrite, admin: User = Depends(platform_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    plan = db.get(TenantPlan, payload.plan_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not plan or not plan.active:
        raise HTTPException(status_code=400, detail="Tenant plan is unavailable")
    now = datetime.now(timezone.utc)
    days = 366 if payload.billing_period == "annual" else 31
    amount = plan.annual_price if payload.billing_period == "annual" else plan.monthly_price
    subscription = db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id))
    if subscription is None:
        subscription = TenantSubscription(
            tenant_id=tenant.id,
            plan_id=plan.id,
            current_period_start=now,
            current_period_end=now + timedelta(days=days),
        )
        db.add(subscription)
    subscription.plan_id = plan.id
    subscription.status = payload.status
    subscription.billing_period = payload.billing_period
    subscription.price_amount = amount
    subscription.currency = plan.currency
    subscription.current_period_start = now
    subscription.current_period_end = now + timedelta(days=days)
    subscription.trial_ends_at = None
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.subscription_updated", entity_type="tenant", entity_id=str(tenant.id), detail=f"{plan.code}:{payload.billing_period}:{payload.status}"))
    db.commit()
    return subscription_payload(subscription, plan)


@router.get("/api/v1/admin/platform/summary")
def platform_summary(_: User = Depends(platform_admin), db: Session = Depends(get_db)):
    tenants = list(db.scalars(select(Tenant)))
    subscriptions = list(db.scalars(select(TenantSubscription)))
    plans = {plan.id: plan for plan in db.scalars(select(TenantPlan))}
    active_subscriptions = []
    monthly_recurring_revenue = 0.0
    annual_contract_value = 0.0
    now = datetime.now(timezone.utc)
    for subscription in subscriptions:
        end = subscription.current_period_end
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
        if subscription.status not in {"trialing", "active"} or end < now:
            continue
        active_subscriptions.append(subscription)
        if subscription.status == "active":
            amount = float(subscription.price_amount)
            monthly_recurring_revenue += amount / 12 if subscription.billing_period == "annual" else amount
            annual_contract_value += amount if subscription.billing_period == "annual" else amount * 12
    return {
        "tenants": len(tenants),
        "active_tenants": sum(1 for tenant in tenants if tenant.active),
        "trialing_subscriptions": sum(1 for row in active_subscriptions if row.status == "trialing"),
        "active_subscriptions": sum(1 for row in active_subscriptions if row.status == "active"),
        "subscription_mrr": round(monthly_recurring_revenue, 2),
        "subscription_acv": round(annual_contract_value, 2),
        "currency": "LSL",
        "connected_meta_pages": db.scalar(select(func.count(TenantSetting.id)).where(TenantSetting.key == "meta.connected", TenantSetting.value == "true")) or 0,
        "verified_domains": db.scalar(select(func.count(TenantDomain.id)).where(TenantDomain.status == "verified")) or 0,
        "plans": [{"id": p.id, "code": p.code, "name": p.name} for p in plans.values()],
    }


@router.get("/api/v1/tenant-admin/onboarding")
def tenant_onboarding(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, admin.tenant_id)
    return onboarding_payload(db, tenant)


@router.get("/api/v1/tenant-admin/staff")
def list_tenant_staff(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    rows = list(db.scalars(
        select(User).where(
            User.tenant_id == admin.tenant_id,
            User.is_tenant_admin.is_(False),
            User.role.in_([UserRole.REVIEWER, UserRole.PUBLISHER]),
        ).order_by(User.created_at.desc())
    ))
    return [{
        "id": row.id,
        "full_name": row.full_name,
        "email": row.email,
        "role": row.role,
        "active": row.is_active,
        "two_factor_enabled": row.two_factor_enabled,
        "created_at": row.created_at,
    } for row in rows]


@router.post("/api/v1/tenant-admin/staff", status_code=201)
def create_tenant_staff(payload: TenantStaffCreate, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    if payload.role not in {UserRole.REVIEWER, UserRole.PUBLISHER}:
        raise HTTPException(status_code=400, detail="Tenant staff role must be reviewer or publisher")
    subscription, plan = current_tenant_subscription(db, admin.tenant_id)
    details = subscription_payload(subscription, plan)
    if not details or not details["usable"]:
        raise HTTPException(status_code=402, detail="An active tenant subscription is required to add staff")
    staff_count = db.scalar(select(func.count(User.id)).where(
        User.tenant_id == admin.tenant_id,
        User.is_tenant_admin.is_(False),
        User.role.in_([UserRole.REVIEWER, UserRole.PUBLISHER]),
        User.is_active.is_(True),
    )) or 0
    if plan and staff_count >= plan.max_staff:
        raise HTTPException(status_code=409, detail=f"Your {plan.name} plan allows up to {plan.max_staff} active staff accounts")
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        tenant_id=admin.tenant_id,
        is_tenant_admin=False,
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.staff_created", entity_type="user", entity_id=str(user.id), detail=payload.role.value))
    db.commit()
    return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role, "active": user.is_active}


@router.patch("/api/v1/tenant-admin/staff/{user_id}/state")
def set_tenant_staff_state(user_id: int, payload: TenantStaffState, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user or user.tenant_id != admin.tenant_id or user.is_tenant_admin or user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER}:
        raise HTTPException(status_code=404, detail="Staff account not found")
    if payload.active and not user.is_active:
        subscription, plan = current_tenant_subscription(db, admin.tenant_id)
        details = subscription_payload(subscription, plan)
        if not details or not details["usable"]:
            raise HTTPException(status_code=402, detail="An active tenant subscription is required to activate staff")
        active_count = db.scalar(select(func.count(User.id)).where(
            User.tenant_id == admin.tenant_id,
            User.is_tenant_admin.is_(False),
            User.role.in_([UserRole.REVIEWER, UserRole.PUBLISHER]),
            User.is_active.is_(True),
        )) or 0
        if plan and active_count >= plan.max_staff:
            raise HTTPException(status_code=409, detail=f"Your {plan.name} plan allows up to {plan.max_staff} active staff accounts")
    user.is_active = payload.active
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.staff_enabled" if payload.active else "tenant.staff_disabled", entity_type="user", entity_id=str(user.id)))
    db.commit()
    return {"id": user.id, "active": user.is_active}


@router.get("/api/v1/tenant-admin/meta")
def tenant_meta_status(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant_id = admin.tenant_id
    token = tenant_setting(db, tenant_id, "meta.page_access_token")
    return {
        "app_id": tenant_setting(db, tenant_id, "meta.app_id"),
        "app_secret_configured": bool(tenant_setting(db, tenant_id, "meta.app_secret")),
        "page_id": tenant_setting(db, tenant_id, "meta.page_id"),
        "page_access_token_configured": bool(token),
        "webhook_verify_token_configured": bool(tenant_setting(db, tenant_id, "meta.webhook_verify_token")),
        "webhook_callback_url": (os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/") + "/api/v1/meta/webhook"),
        "graph_api_version": tenant_setting(db, tenant_id, "meta.graph_api_version") or "v24.0",
        "connected": tenant_setting(db, tenant_id, "meta.connected") == "true",
        "page_name": tenant_setting(db, tenant_id, "meta.page_name"),
    }


@router.put("/api/v1/tenant-admin/meta")
def save_tenant_meta(payload: TenantMetaWrite, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant_id = admin.tenant_id
    page_id = ensure_facebook_page_available(db, payload.page_id, tenant_id)
    set_tenant_setting(db, tenant_id, "meta.app_id", payload.app_id)
    set_tenant_setting(db, tenant_id, "meta.page_id", page_id)
    set_tenant_setting(db, tenant_id, "meta.graph_api_version", payload.graph_api_version)
    if payload.app_secret is not None:
        set_tenant_setting(db, tenant_id, "meta.app_secret", payload.app_secret.get_secret_value(), encrypted=True)
    if payload.page_access_token is not None:
        set_tenant_setting(db, tenant_id, "meta.page_access_token", payload.page_access_token.get_secret_value(), encrypted=True)
    if payload.webhook_verify_token is not None:
        set_tenant_setting(db, tenant_id, "meta.webhook_verify_token", payload.webhook_verify_token.get_secret_value(), encrypted=True)
    set_tenant_setting(db, tenant_id, "meta.connected", "false")
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.meta_updated", entity_type="tenant", entity_id=str(tenant_id)))
    db.commit()
    return tenant_meta_status(admin, db)


@router.post("/api/v1/tenant-admin/meta/test")
def test_tenant_meta(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant_id = admin.tenant_id
    page_id = tenant_setting(db, tenant_id, "meta.page_id")
    token = tenant_setting(db, tenant_id, "meta.page_access_token")
    version = tenant_setting(db, tenant_id, "meta.graph_api_version") or "v24.0"
    if not page_id or not token:
        raise HTTPException(status_code=400, detail="Facebook Page ID and Page access token are required")
    response = httpx.get(
        f"https://graph.facebook.com/{version}/{page_id}",
        params={"fields": "id,name", "access_token": token},
        timeout=20.0,
    )
    data = response.json() if response.content else {}
    if response.is_error:
        raise HTTPException(status_code=502, detail=data.get("error", {}).get("message") or "Meta connection failed")
    verified_page_id = ensure_facebook_page_available(db, str(data.get("id") or page_id), tenant_id)
    set_tenant_setting(db, tenant_id, "meta.connected", "true")
    set_tenant_setting(db, tenant_id, "meta.page_name", str(data.get("name") or ""))
    tenant = db.get(Tenant, tenant_id)
    tenant.facebook_page_id = verified_page_id
    tenant.facebook_page_name = str(data.get("name") or tenant.name)
    db.commit()
    return {"connected": True, "page_id": tenant.facebook_page_id, "page_name": tenant.facebook_page_name}
