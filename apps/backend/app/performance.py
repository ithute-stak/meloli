from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .meta_service import MetaError, fetch_post_performance
from .models import Campaign, CampaignPerformance, CampaignPerformanceSnapshot, CampaignStatus, User, UserRole
from .security import decode_access_token, decrypt_secret

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class CampaignPerformanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    campaign_id: int
    impressions: int | None
    reach: int | None
    engaged_users: int | None
    clicks: int | None
    reactions: int | None
    comments: int | None
    shares: int | None
    video_views: int | None
    synced_at: datetime


class PerformanceSummary(BaseModel):
    campaigns_published: int
    campaigns_with_metrics: int
    impressions: int
    reach: int
    engaged_users: int
    clicks: int
    reactions: int
    comments: int
    shares: int
    video_views: int
    engagement_rate: float
    click_rate: float


class BulkSyncResult(BaseModel):
    eligible: int
    synced: int
    failed: int
    failures: list[str]


def authenticated_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
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


def publisher_user(user: User = Depends(authenticated_user)) -> User:
    if user.role not in {UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Publisher or super admin access required")
    return user


def setting(db: Session, key: str) -> str | None:
    from .models import SystemSetting

    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if not row or not row.value:
        return None
    return decrypt_secret(row.value) if row.encrypted else row.value


def campaign_for_user(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role == UserRole.ADVERTISER and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this campaign")
    return campaign


def _summary(rows: list[CampaignPerformance], published_count: int) -> PerformanceSummary:
    def total(name: str) -> int:
        return sum(int(getattr(row, name) or 0) for row in rows)

    impressions = total("impressions")
    reach = total("reach")
    engaged = total("engaged_users")
    clicks = total("clicks")
    reactions = total("reactions")
    comments = total("comments")
    shares = total("shares")
    video_views = total("video_views")
    engagement_events = engaged or (reactions + comments + shares)
    engagement_rate = round((engagement_events / reach) * 100, 2) if reach else 0.0
    click_rate = round((clicks / reach) * 100, 2) if reach else 0.0
    return PerformanceSummary(
        campaigns_published=published_count,
        campaigns_with_metrics=len(rows),
        impressions=impressions,
        reach=reach,
        engaged_users=engaged,
        clicks=clicks,
        reactions=reactions,
        comments=comments,
        shares=shares,
        video_views=video_views,
        engagement_rate=engagement_rate,
        click_rate=click_rate,
    )


def _sync_one(db: Session, campaign: Campaign, token: str, version: str) -> CampaignPerformance:
    if campaign.status != CampaignStatus.PUBLISHED or not campaign.facebook_post_id:
        raise MetaError("Only published Facebook campaigns can sync performance")
    result = fetch_post_performance(campaign.facebook_post_id, token, version)
    row = db.scalar(select(CampaignPerformance).where(CampaignPerformance.campaign_id == campaign.id))
    if row is None:
        row = CampaignPerformance(campaign_id=campaign.id)
        db.add(row)
    row.impressions = result.impressions
    row.reach = result.reach
    row.engaged_users = result.engaged_users
    row.clicks = result.clicks
    row.reactions = result.reactions
    row.comments = result.comments
    row.shares = result.shares
    row.video_views = result.video_views
    row.synced_at = datetime.now(timezone.utc)
    db.add(CampaignPerformanceSnapshot(
        campaign_id=campaign.id,
        impressions=result.impressions,
        reach=result.reach,
        engaged_users=result.engaged_users,
        clicks=result.clicks,
        reactions=result.reactions,
        comments=result.comments,
        shares=result.shares,
        video_views=result.video_views,
        captured_at=row.synced_at,
    ))
    return row


@router.get("/api/v1/campaigns/{campaign_id}/performance", response_model=CampaignPerformanceOut | None)
def campaign_performance(campaign_id: int, user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    campaign_for_user(db, campaign_id, user)
    return db.scalar(select(CampaignPerformance).where(CampaignPerformance.campaign_id == campaign_id))


@router.post("/api/v1/campaigns/{campaign_id}/performance/sync", response_model=CampaignPerformanceOut)
def sync_campaign_performance(campaign_id: int, _: User = Depends(publisher_user), db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    token = setting(db, "meta.page_access_token")
    version = setting(db, "meta.graph_api_version")
    if not token or not version:
        raise HTTPException(status_code=409, detail="Meta Page access token and Graph API version are required")
    try:
        row = _sync_one(db, campaign, token, version)
    except MetaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return row


@router.post("/api/v1/admin/performance/sync", response_model=BulkSyncResult)
def sync_all_performance(_: User = Depends(publisher_user), db: Session = Depends(get_db)):
    token = setting(db, "meta.page_access_token")
    version = setting(db, "meta.graph_api_version")
    if not token or not version:
        raise HTTPException(status_code=409, detail="Meta Page access token and Graph API version are required")
    campaigns = list(db.scalars(select(Campaign).where(Campaign.status == CampaignStatus.PUBLISHED, Campaign.facebook_post_id.is_not(None)).order_by(Campaign.published_at.desc())))
    synced = 0
    failures: list[str] = []
    for campaign in campaigns:
        try:
            _sync_one(db, campaign, token, version)
            db.commit()
            synced += 1
        except MetaError as exc:
            db.rollback()
            failures.append(f"Campaign {campaign.id}: {str(exc)[:180]}")
    return BulkSyncResult(eligible=len(campaigns), synced=synced, failed=len(failures), failures=failures[:20])


@router.get("/api/v1/advertiser/performance/summary", response_model=PerformanceSummary)
def advertiser_performance_summary(user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    if user.role != UserRole.ADVERTISER:
        raise HTTPException(status_code=403, detail="Advertiser access required")
    published_count = db.scalar(select(func.count(Campaign.id)).where(Campaign.advertiser_id == user.id, Campaign.status == CampaignStatus.PUBLISHED)) or 0
    rows = list(db.scalars(select(CampaignPerformance).join(Campaign, Campaign.id == CampaignPerformance.campaign_id).where(Campaign.advertiser_id == user.id)))
    return _summary(rows, int(published_count))


@router.get("/api/v1/admin/performance/summary", response_model=PerformanceSummary)
def admin_performance_summary(user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    if user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Meloli staff access required")
    published_count = db.scalar(select(func.count(Campaign.id)).where(Campaign.status == CampaignStatus.PUBLISHED)) or 0
    rows = list(db.scalars(select(CampaignPerformance)))
    return _summary(rows, int(published_count))
