from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from .models import CampaignStatus, UserRole


class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    business_name: str | None = Field(default=None, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    business_name: str | None
    email: EmailStr
    phone: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    price: float
    currency: str
    posts_included: int
    active: bool


class CampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    caption: str = Field(min_length=3, max_length=5000)
    package_code: str = Field(min_length=2, max_length=50)
    preferred_publish_at: datetime | None = None
    media_url: str | None = Field(default=None, max_length=1000)
    destination_url: str | None = Field(default=None, max_length=1000)


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    advertiser_id: int
    package_id: int
    title: str
    caption: str
    media_url: str | None
    destination_url: str | None
    preferred_publish_at: datetime | None
    scheduled_publish_at: datetime | None
    status: CampaignStatus
    reviewer_note: str | None
    facebook_post_id: str | None
    facebook_post_url: str | None
    created_at: datetime
    updated_at: datetime


class CampaignDecision(BaseModel):
    status: CampaignStatus
    reviewer_note: str | None = Field(default=None, max_length=3000)
    scheduled_publish_at: datetime | None = None


class MetaIntegrationUpdate(BaseModel):
    app_id: str = Field(min_length=3, max_length=200)
    app_secret: SecretStr | None = None
    page_id: str = Field(min_length=3, max_length=200)
    page_access_token: SecretStr | None = None
    webhook_verify_token: SecretStr | None = None
    webhook_callback_url: str | None = Field(default=None, max_length=500)
    graph_api_version: str | None = Field(default=None, max_length=32)


class MetaIntegrationStatus(BaseModel):
    configured: bool
    connected: bool
    app_id: str | None = None
    page_id: str | None = None
    webhook_callback_url: str | None = None
    graph_api_version: str | None = None
    app_secret_configured: bool = False
    page_access_token_configured: bool = False
    webhook_verify_token_configured: bool = False
    updated_at: datetime | None = None
