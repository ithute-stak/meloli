from datetime import datetime, timezone
from enum import StrEnum

from fastapi import FastAPI
from pydantic import BaseModel, EmailStr, Field, SecretStr

app = FastAPI(title="Meloli Advertising API", version="0.2.0")


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PAYMENT_PENDING = "payment_pending"
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    REJECTED = "rejected"


class CampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    advertiser_name: str = Field(min_length=2, max_length=160)
    advertiser_email: EmailStr
    caption: str = Field(min_length=3, max_length=5000)
    preferred_publish_at: datetime | None = None
    package_code: str = Field(min_length=2, max_length=50)


class Campaign(CampaignCreate):
    id: int
    status: CampaignStatus = CampaignStatus.SUBMITTED
    created_at: datetime


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


# Temporary process-local state for the foundation branch. The persistence layer
# will move this to encrypted database-backed system settings before production.
_meta_state: dict[str, object] = {
    "configured": False,
    "connected": False,
    "app_id": None,
    "page_id": None,
    "webhook_callback_url": None,
    "graph_api_version": None,
    "app_secret": None,
    "page_access_token": None,
    "webhook_verify_token": None,
    "updated_at": None,
}


def _meta_status() -> MetaIntegrationStatus:
    return MetaIntegrationStatus(
        configured=bool(_meta_state["configured"]),
        connected=bool(_meta_state["connected"]),
        app_id=_meta_state["app_id"],
        page_id=_meta_state["page_id"],
        webhook_callback_url=_meta_state["webhook_callback_url"],
        graph_api_version=_meta_state["graph_api_version"],
        app_secret_configured=bool(_meta_state["app_secret"]),
        page_access_token_configured=bool(_meta_state["page_access_token"]),
        webhook_verify_token_configured=bool(_meta_state["webhook_verify_token"]),
        updated_at=_meta_state["updated_at"],
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "meloli-api"}


@app.get("/api/v1/campaigns", response_model=list[Campaign])
def list_campaigns():
    return []


@app.post("/api/v1/campaigns", response_model=Campaign, status_code=201)
def create_campaign(payload: CampaignCreate):
    return Campaign(
        id=1,
        status=CampaignStatus.SUBMITTED,
        created_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )


@app.get("/api/v1/system/integrations/meta", response_model=MetaIntegrationStatus)
def get_meta_integration():
    """Return only non-secret Meta configuration and secret-presence flags."""
    return _meta_status()


@app.put("/api/v1/system/integrations/meta", response_model=MetaIntegrationStatus)
def update_meta_integration(payload: MetaIntegrationUpdate):
    """Create or rotate Meta credentials without ever returning secret values."""
    _meta_state["app_id"] = payload.app_id
    _meta_state["page_id"] = payload.page_id
    _meta_state["webhook_callback_url"] = payload.webhook_callback_url
    _meta_state["graph_api_version"] = payload.graph_api_version
    if payload.app_secret is not None:
        _meta_state["app_secret"] = payload.app_secret.get_secret_value()
    if payload.page_access_token is not None:
        _meta_state["page_access_token"] = payload.page_access_token.get_secret_value()
    if payload.webhook_verify_token is not None:
        _meta_state["webhook_verify_token"] = payload.webhook_verify_token.get_secret_value()
    _meta_state["configured"] = bool(
        _meta_state["app_id"] and _meta_state["page_id"] and _meta_state["page_access_token"]
    )
    _meta_state["connected"] = False
    _meta_state["updated_at"] = datetime.now(timezone.utc)
    return _meta_status()


@app.post("/api/v1/system/integrations/meta/test", response_model=MetaIntegrationStatus)
def test_meta_integration():
    """Foundation endpoint. Real Graph API verification is added with the Meta connector."""
    # Keep false until the backend has actually verified Page access with Meta.
    _meta_state["connected"] = False
    return _meta_status()
