import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine, get_db
from .models import AdvertisingPackage, Campaign, CampaignStatus, SystemSetting, User, UserRole
from .schemas import (
    AuthToken,
    CampaignCreate,
    CampaignDecision,
    CampaignOut,
    MetaIntegrationStatus,
    MetaIntegrationUpdate,
    PackageOut,
    UserLogin,
    UserOut,
    UserRegister,
)
from .security import create_access_token, decode_access_token, encrypt_secret, hash_password, verify_password

bearer = HTTPBearer(auto_error=False)

DEFAULT_PACKAGES = [
    {"code": "STANDARD", "name": "Standard Post", "description": "One approved Facebook Page post on the Meloli Airwaves publishing schedule.", "price": 450, "posts_included": 1},
    {"code": "PREMIUM", "name": "Premium Placement", "description": "One priority-scheduled promotional post with enhanced editorial placement.", "price": 650, "posts_included": 1},
    {"code": "WEEKLY", "name": "Weekly Campaign", "description": "A coordinated week-long package containing up to four approved posts.", "price": 1800, "posts_included": 4},
]


def seed_data() -> None:
    db = SessionLocal()
    try:
        for package_data in DEFAULT_PACKAGES:
            if not db.scalar(select(AdvertisingPackage).where(AdvertisingPackage.code == package_data["code"])):
                db.add(AdvertisingPackage(**package_data))
        admin_email = os.getenv("SUPER_ADMIN_EMAIL")
        admin_password = os.getenv("SUPER_ADMIN_PASSWORD")
        if admin_email and admin_password and not db.scalar(select(User).where(User.email == admin_email.lower())):
            db.add(User(full_name=os.getenv("SUPER_ADMIN_NAME", "Meloli Super Admin"), email=admin_email.lower(), password_hash=hash_password(admin_password), role=UserRole.SUPER_ADMIN))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_data()
    yield


app = FastAPI(title="Meloli Advertising API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = int(decode_access_token(credentials.credentials)["sub"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable")
    return user


def staff_user(user: User = Depends(current_user)) -> User:
    if user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Meloli staff access required")
    return user


def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return user


def get_setting(db: Session, key: str) -> SystemSetting | None:
    return db.scalar(select(SystemSetting).where(SystemSetting.key == key))


def set_setting(db: Session, key: str, value: str | None, encrypted: bool = False) -> None:
    item = get_setting(db, key)
    stored = encrypt_secret(value) if encrypted and value is not None else value
    if item:
        item.value = stored
        item.encrypted = encrypted
    else:
        db.add(SystemSetting(key=key, value=stored, encrypted=encrypted))


def meta_status(db: Session) -> MetaIntegrationStatus:
    def value(key: str) -> str | None:
        item = get_setting(db, key)
        return item.value if item and not item.encrypted else None

    def present(key: str) -> bool:
        item = get_setting(db, key)
        return bool(item and item.value)

    tracked = [get_setting(db, key) for key in ("meta.app_id", "meta.page_id", "meta.app_secret", "meta.page_access_token", "meta.webhook_verify_token")]
    updated = [item.updated_at for item in tracked if item is not None]
    app_id = value("meta.app_id")
    page_id = value("meta.page_id")
    return MetaIntegrationStatus(
        configured=bool(app_id and page_id and present("meta.page_access_token")),
        connected=value("meta.connected") == "true",
        app_id=app_id,
        page_id=page_id,
        webhook_callback_url=value("meta.webhook_callback_url"),
        graph_api_version=value("meta.graph_api_version"),
        app_secret_configured=present("meta.app_secret"),
        page_access_token_configured=present("meta.page_access_token"),
        webhook_verify_token_configured=present("meta.webhook_verify_token"),
        updated_at=max(updated) if updated else None,
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "meloli-api", "version": "0.3.0"}


@app.post("/api/v1/auth/register", response_model=AuthToken, status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account already exists for this email")
    user = User(full_name=payload.full_name, business_name=payload.business_name, email=email, phone=payload.phone, password_hash=hash_password(payload.password), role=UserRole.ADVERTISER)
    db.add(user)
    db.commit()
    db.refresh(user)
    return AuthToken(access_token=create_access_token(user.id, user.role.value), user=user)


@app.post("/api/v1/auth/login", response_model=AuthToken)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    return AuthToken(access_token=create_access_token(user.id, user.role.value), user=user)


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/v1/packages", response_model=list[PackageOut])
def list_packages(db: Session = Depends(get_db)):
    return list(db.scalars(select(AdvertisingPackage).where(AdvertisingPackage.active.is_(True)).order_by(AdvertisingPackage.price)))


@app.get("/api/v1/campaigns", response_model=list[CampaignOut])
def list_campaigns(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Campaign).order_by(Campaign.created_at.desc())
    if user.role == UserRole.ADVERTISER:
        query = query.where(Campaign.advertiser_id == user.id)
    return list(db.scalars(query))


@app.post("/api/v1/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(payload: CampaignCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    package = db.scalar(select(AdvertisingPackage).where(AdvertisingPackage.code == payload.package_code.upper(), AdvertisingPackage.active.is_(True)))
    if not package:
        raise HTTPException(status_code=400, detail="Advertising package is unavailable")
    campaign = Campaign(advertiser_id=user.id, package_id=package.id, title=payload.title, caption=payload.caption, media_url=payload.media_url, destination_url=payload.destination_url, preferred_publish_at=payload.preferred_publish_at, status=CampaignStatus.PAYMENT_PENDING)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


@app.patch("/api/v1/campaigns/{campaign_id}/decision", response_model=CampaignOut)
def decide_campaign(campaign_id: int, payload: CampaignDecision, _: User = Depends(staff_user), db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    allowed = {CampaignStatus.IN_REVIEW, CampaignStatus.CHANGES_REQUESTED, CampaignStatus.APPROVED, CampaignStatus.SCHEDULED, CampaignStatus.REJECTED}
    if payload.status not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported editorial decision")
    if payload.status == CampaignStatus.CHANGES_REQUESTED and not payload.reviewer_note:
        raise HTTPException(status_code=400, detail="A change request must include a reviewer note")
    campaign.status = payload.status
    campaign.reviewer_note = payload.reviewer_note
    if payload.status == CampaignStatus.SCHEDULED:
        if not payload.scheduled_publish_at:
            raise HTTPException(status_code=400, detail="Scheduled campaigns require a publishing date")
        campaign.scheduled_publish_at = payload.scheduled_publish_at
    db.commit()
    db.refresh(campaign)
    return campaign


@app.get("/api/v1/system/integrations/meta", response_model=MetaIntegrationStatus)
def get_meta_integration(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    return meta_status(db)


@app.put("/api/v1/system/integrations/meta", response_model=MetaIntegrationStatus)
def update_meta_integration(payload: MetaIntegrationUpdate, _: User = Depends(super_admin), db: Session = Depends(get_db)):
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
    db.commit()
    return meta_status(db)


@app.post("/api/v1/system/integrations/meta/test", response_model=MetaIntegrationStatus)
def test_meta_integration(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    set_setting(db, "meta.connected", "false")
    db.commit()
    return meta_status(db)
