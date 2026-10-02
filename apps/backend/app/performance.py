from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_db
from .meta_service import MetaError, fetch_post_performance
from .models import Campaign, CampaignPerformance, CampaignPerformanceSnapshot, CampaignStatus, User, UserRole
from .security import validate_token_user
from .tenancy import tenant_setting

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
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid, expired or revoked session") from exc


def publisher_user(user: User = Depends(authenticated_user)) -> User:
    if user.role not in {UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Publisher or super admin access required")
    return user


def campaign_for_user(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id or campaign.tenant_id != user.tenant_id:
            raise HTTPException(status_code=403, detail="Campaign belongs to another portal")
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin and campaign.advertiser_id != user.id:
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
def sync_campaign_performance(campaign_id: int, publisher: User = Depends(publisher_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, publisher)
    if not campaign.tenant_id:
        raise HTTPException(status_code=409, detail="Campaign is not attached to a tenant")
    token = tenant_setting(db, campaign.tenant_id, "meta.page_access_token")
    version = tenant_setting(db, campaign.tenant_id, "meta.graph_api_version") or "v24.0"
    if not token:
        raise HTTPException(status_code=409, detail="This portal has no Meta Page access token configured")
    try:
        row = _sync_one(db, campaign, token, version)
    except MetaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return row


@router.post("/api/v1/admin/performance/sync", response_model=BulkSyncResult)
def sync_all_performance(publisher: User = Depends(publisher_user), db: Session = Depends(get_db)):
    query = select(Campaign).where(
        Campaign.status == CampaignStatus.PUBLISHED,
        Campaign.facebook_post_id.is_not(None),
    )
    if publisher.role != UserRole.SUPER_ADMIN:
        if not publisher.tenant_id:
            raise HTTPException(status_code=403, detail="Publisher account is not attached to a portal")
        query = query.where(Campaign.tenant_id == publisher.tenant_id)
    campaigns = list(db.scalars(query.order_by(Campaign.published_at.desc())))
    synced = 0
    failures: list[str] = []
    for campaign in campaigns:
        if not campaign.tenant_id:
            failures.append(f"Campaign {campaign.id}: campaign is not attached to a tenant")
            continue
        token = tenant_setting(db, campaign.tenant_id, "meta.page_access_token")
        version = tenant_setting(db, campaign.tenant_id, "meta.graph_api_version") or "v24.0"
        if not token:
            failures.append(f"Campaign {campaign.id}: portal Meta Page access token is not configured")
            continue
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
    campaign_filter = [Campaign.status == CampaignStatus.PUBLISHED]
    performance_query = select(CampaignPerformance).join(Campaign, Campaign.id == CampaignPerformance.campaign_id)
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id:
            raise HTTPException(status_code=403, detail="Staff account is not attached to a portal")
        campaign_filter.append(Campaign.tenant_id == user.tenant_id)
        performance_query = performance_query.where(Campaign.tenant_id == user.tenant_id)
    published_count = db.scalar(select(func.count(Campaign.id)).where(*campaign_filter)) or 0
    rows = list(db.scalars(performance_query))
    return _summary(rows, int(published_count))
