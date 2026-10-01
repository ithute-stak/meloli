from datetime import datetime
from enum import StrEnum
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(title="Meloli Advertising API", version="0.1.0")

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

@app.get("/health")
def health():
    return {"status": "ok", "service": "meloli-api"}

@app.get("/api/v1/campaigns", response_model=list[Campaign])
def list_campaigns():
    return []

@app.post("/api/v1/campaigns", response_model=Campaign, status_code=201)
def create_campaign(payload: CampaignCreate):
    return Campaign(id=1, status=CampaignStatus.SUBMITTED, created_at=datetime.utcnow(), **payload.model_dump())
