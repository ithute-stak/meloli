import os
import re
import secrets
from datetime import datetime, timezone

import httpx
import dns.resolver
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Tenant, TenantDomain, TenantSetting, User, UserRole
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


class DomainWrite(BaseModel):
    hostname: str = Field(min_length=4, max_length=255)


class TenantMetaWrite(BaseModel):
    app_id: str | None = Field(default=None, max_length=200)
    app_secret: SecretStr | None = None
    page_id: str | None = Field(default=None, max_length=200)
    page_access_token: SecretStr | None = None
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
        facebook_page_id=payload.facebook_page_id.strip() if payload.facebook_page_id else None,
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


@router.get("/api/v1/tenant-admin/profile")
def tenant_admin_profile(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, admin.tenant_id)
    domains = list(db.scalars(select(TenantDomain).where(TenantDomain.tenant_id == admin.tenant_id).order_by(TenantDomain.created_at.desc())))
    return {
        **tenant_payload(tenant),
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
    tenant.name = payload.name.strip()
    tenant.facebook_page_name = payload.facebook_page_name.strip() if payload.facebook_page_name else None
    tenant.facebook_page_id = payload.facebook_page_id.strip() if payload.facebook_page_id else None
    tenant.logo_url = payload.logo_url
    tenant.accent_color = payload.accent_color
    db.add(AuditLog(actor_user_id=admin.id, action="tenant.profile_updated", entity_type="tenant", entity_id=str(tenant.id), detail=tenant.slug))
    db.commit()
    return tenant_payload(tenant)


@router.post("/api/v1/tenant-admin/domains", status_code=201)
def add_custom_domain(payload: DomainWrite, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
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


@router.get("/api/v1/tenant-admin/meta")
def tenant_meta_status(admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant_id = admin.tenant_id
    token = tenant_setting(db, tenant_id, "meta.page_access_token")
    return {
        "app_id": tenant_setting(db, tenant_id, "meta.app_id"),
        "app_secret_configured": bool(tenant_setting(db, tenant_id, "meta.app_secret")),
        "page_id": tenant_setting(db, tenant_id, "meta.page_id"),
        "page_access_token_configured": bool(token),
        "graph_api_version": tenant_setting(db, tenant_id, "meta.graph_api_version") or "v24.0",
        "connected": tenant_setting(db, tenant_id, "meta.connected") == "true",
        "page_name": tenant_setting(db, tenant_id, "meta.page_name"),
    }


@router.put("/api/v1/tenant-admin/meta")
def save_tenant_meta(payload: TenantMetaWrite, admin: User = Depends(tenant_admin), db: Session = Depends(get_db)):
    tenant_id = admin.tenant_id
    set_tenant_setting(db, tenant_id, "meta.app_id", payload.app_id)
    set_tenant_setting(db, tenant_id, "meta.page_id", payload.page_id)
    set_tenant_setting(db, tenant_id, "meta.graph_api_version", payload.graph_api_version)
    if payload.app_secret is not None:
        set_tenant_setting(db, tenant_id, "meta.app_secret", payload.app_secret.get_secret_value(), encrypted=True)
    if payload.page_access_token is not None:
        set_tenant_setting(db, tenant_id, "meta.page_access_token", payload.page_access_token.get_secret_value(), encrypted=True)
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
    set_tenant_setting(db, tenant_id, "meta.connected", "true")
    set_tenant_setting(db, tenant_id, "meta.page_name", str(data.get("name") or ""))
    tenant = db.get(Tenant, tenant_id)
    tenant.facebook_page_id = str(data.get("id") or page_id)
    tenant.facebook_page_name = str(data.get("name") or tenant.name)
    db.commit()
    return {"connected": True, "page_id": tenant.facebook_page_id, "page_name": tenant.facebook_page_name}
