from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from .models import CampaignStatus, PaymentStatus, PublicationStatus, UserRole


class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    business_name: str | None = Field(default=None, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    otp_code: str | None = Field(default=None, min_length=6, max_length=8)


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


class PackageWrite(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=3000)
    price: float = Field(gt=0)
    currency: str = Field(default="LSL", min_length=3, max_length=8)
    posts_included: int = Field(default=1, ge=1, le=100)
    active: bool = True


class CampaignMediaCreate(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    content_type: str = Field(min_length=3, max_length=120)


class CampaignMediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    content_type: str
    position: int


class CampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    caption: str = Field(min_length=3, max_length=5000)
    package_code: str = Field(min_length=2, max_length=50)
    preferred_publish_at: datetime | None = None
    media_url: str | None = Field(default=None, max_length=1000)
    media_items: list[CampaignMediaCreate] = Field(default_factory=list, max_length=10)
    destination_url: str | None = Field(default=None, max_length=1000)


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    advertiser_id: int
    package_id: int
    title: str
    caption: str
    media_url: str | None
    media_items: list[CampaignMediaOut] = Field(default_factory=list)
    destination_url: str | None
    preferred_publish_at: datetime | None
    scheduled_publish_at: datetime | None
    status: CampaignStatus
    reviewer_note: str | None
    proof_status: str
    proof_requested_at: datetime | None
    proof_approved_at: datetime | None
    proof_feedback: str | None
    proof_requested_by_user_id: int | None
    proof_approved_by_user_id: int | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    cancelled_by_user_id: int | None
    facebook_post_id: str | None
    facebook_post_url: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignDecision(BaseModel):
    status: CampaignStatus
    reviewer_note: str | None = Field(default=None, max_length=3000)
    scheduled_publish_at: datetime | None = None


class PaymentCreate(BaseModel):
    method: str = Field(default="manual", min_length=2, max_length=80)
    reference: str | None = Field(default=None, max_length=160)
    promo_code: str | None = Field(default=None, max_length=50)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    campaign_id: int
    amount: float
    currency: str
    method: str
    reference: str | None
    status: PaymentStatus
    paid_at: datetime | None
    created_at: datetime


class PaymentDecision(BaseModel):
    status: PaymentStatus
    reference: str | None = Field(default=None, max_length=160)


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    campaign_id: int
    status: PublicationStatus
    attempt_number: int
    external_post_id: str | None
    external_post_url: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class PublishResult(BaseModel):
    campaign: CampaignOut
    publication: PublicationOut


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    kind: str
    title: str
    message: str
    read_at: datetime | None
    created_at: datetime


class ReportSummary(BaseModel):
    advertisers: int
    campaigns: int
    awaiting_review: int
    scheduled: int
    published: int
    paid_payments: int
    revenue: float
    currency: str = "LSL"
    failed_publications: int


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
    page_name: str | None = None
    webhook_callback_url: str | None = None
    graph_api_version: str | None = None
    app_secret_configured: bool = False
    page_access_token_configured: bool = False
    webhook_verify_token_configured: bool = False
    updated_at: datetime | None = None
