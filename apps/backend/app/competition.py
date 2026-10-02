from collections import defaultdict
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuditLog, Campaign, CompetitionComment, CompetitionReaction, User, UserRole
from .security import validate_token_user
from .tenancy import tenant_setting

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class ImportedReaction(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    user_name: str | None = Field(default=None, max_length=255)


class ImportedComment(BaseModel):
    comment_id: str = Field(min_length=1, max_length=255)
    message: str | None = None
    author_name: str | None = Field(default=None, max_length=255)
    reactions: list[ImportedReaction] = Field(default_factory=list)


class CompetitionImport(BaseModel):
    comments: list[ImportedComment] = Field(default_factory=list, max_length=5000)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return validate_token_user(credentials.credentials, db)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid, expired or revoked session") from exc


def campaign_for_user(db: Session, campaign_id: int, user: User) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.tenant_id and campaign.tenant_id and user.tenant_id != campaign.tenant_id:
        raise HTTPException(status_code=403, detail="Campaign belongs to another portal")
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this campaign")
    return campaign


def require_competition(campaign: Campaign) -> None:
    if campaign.engagement_mode != "competition_one_comment":
        raise HTTPException(status_code=409, detail="This campaign is not using one-person/one-comment competition mode")


def _paginate(url: str, params: dict) -> list[dict]:
    rows: list[dict] = []
    current_url = url
    current_params = params
    for _ in range(100):
        response = httpx.get(current_url, params=current_params, timeout=30.0)
        payload = response.json() if response.content else {}
        if response.is_error:
            message = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
            raise RuntimeError(message or f"Meta returned HTTP {response.status_code}")
        rows.extend(payload.get("data") or [])
        next_url = (payload.get("paging") or {}).get("next")
        if not next_url:
            break
        current_url = next_url
        current_params = {}
    return rows


def _fetch_comment_voters(comment_id: str, version: str, token: str) -> list[dict]:
    base = f"https://graph.facebook.com/{version}/{comment_id}"
    errors: list[str] = []
    for edge in ("likes", "reactions"):
        try:
            return _paginate(
                f"{base}/{edge}",
                {"fields": "id,name", "limit": 500, "access_token": token},
            )
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("Unable to read comment voters: " + " | ".join(errors))


def _fetch_facebook_comments(campaign: Campaign, db: Session) -> list[ImportedComment]:
    if not campaign.facebook_post_id:
        raise HTTPException(status_code=409, detail="Campaign has not been published to Facebook yet")
    if not campaign.tenant_id:
        raise HTTPException(status_code=409, detail="Campaign is not attached to a tenant")

    token = tenant_setting(db, campaign.tenant_id, "meta.page_access_token")
    version = tenant_setting(db, campaign.tenant_id, "meta.graph_api_version") or "v24.0"
    if not token:
        raise HTTPException(status_code=409, detail="This portal has no Facebook Page access token configured")

    comments = _paginate(
        f"https://graph.facebook.com/{version}/{campaign.facebook_post_id}/comments",
        {"fields": "id,message,from", "limit": 100, "access_token": token},
    )
    imported: list[ImportedComment] = []
    for item in comments:
        comment_id = str(item.get("id") or "")
        if not comment_id:
            continue
        voters = _fetch_comment_voters(comment_id, version, token)
        imported.append(
            ImportedComment(
                comment_id=comment_id,
                message=item.get("message"),
                author_name=(item.get("from") or {}).get("name"),
                reactions=[
                    ImportedReaction(user_id=str(v.get("id")), user_name=v.get("name"))
                    for v in voters
                    if v.get("id")
                ],
            )
        )
    return imported


def _replace_results(db: Session, campaign: Campaign, comments: list[ImportedComment]) -> dict:
    db.execute(delete(CompetitionReaction).where(CompetitionReaction.campaign_id == campaign.id))
    db.execute(delete(CompetitionComment).where(CompetitionComment.campaign_id == campaign.id))
    db.flush()

    seen_by_user: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str | None] = {}
    deduped: dict[str, dict[str, ImportedReaction]] = {}
    for comment in comments:
        per_comment: dict[str, ImportedReaction] = {}
        for reaction in comment.reactions:
            per_comment[reaction.user_id] = reaction
            seen_by_user[reaction.user_id].add(comment.comment_id)
            names[reaction.user_id] = reaction.user_name or names.get(reaction.user_id)
        deduped[comment.comment_id] = per_comment

    invalid_users = {user_id for user_id, comment_ids in seen_by_user.items() if len(comment_ids) > 1}
    comment_rows: list[CompetitionComment] = []
    raw_total = 0
    valid_total = 0

    for item in comments:
        reactions = deduped.get(item.comment_id, {})
        raw = len(reactions)
        valid = sum(1 for user_id in reactions if user_id not in invalid_users)
        row = CompetitionComment(
            campaign_id=campaign.id,
            external_comment_id=item.comment_id,
            message=item.message,
            author_name=item.author_name,
            raw_likes=raw,
            valid_likes=valid,
            invalid_likes=raw - valid,
            synced_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.flush()
        comment_rows.append(row)
        raw_total += raw
        valid_total += valid
        for user_id, reaction in reactions.items():
            db.add(
                CompetitionReaction(
                    campaign_id=campaign.id,
                    comment_id=row.id,
                    external_user_id=user_id,
                    external_user_name=reaction.user_name or names.get(user_id),
                    valid=user_id not in invalid_users,
                    synced_at=datetime.now(timezone.utc),
                )
            )

    db.flush()
    return {
        "campaign_id": campaign.id,
        "mode": campaign.engagement_mode,
        "comments": len(comment_rows),
        "raw_likes": raw_total,
        "valid_likes": valid_total,
        "invalid_likes": raw_total - valid_total,
        "participating_people": len(seen_by_user),
        "disqualified_people": len(invalid_users),
        "rule": "A person who likes more than one different comment contributes zero valid likes to this campaign.",
    }


def _result_payload(db: Session, campaign: Campaign) -> dict:
    comments = list(db.scalars(
        select(CompetitionComment)
        .where(CompetitionComment.campaign_id == campaign.id)
        .order_by(CompetitionComment.valid_likes.desc(), CompetitionComment.raw_likes.desc(), CompetitionComment.id)
    ))
    reactions = list(db.scalars(select(CompetitionReaction).where(CompetitionReaction.campaign_id == campaign.id)))
    user_comments: dict[str, set[int]] = defaultdict(set)
    user_names: dict[str, str | None] = {}
    for reaction in reactions:
        user_comments[reaction.external_user_id].add(reaction.comment_id)
        user_names[reaction.external_user_id] = reaction.external_user_name

    disqualified = [
        {
            "user_id": user_id,
            "user_name": user_names.get(user_id),
            "comments_liked": len(comment_ids),
        }
        for user_id, comment_ids in user_comments.items()
        if len(comment_ids) > 1
    ]
    return {
        "campaign_id": campaign.id,
        "title": campaign.title,
        "mode": campaign.engagement_mode,
        "rule": "One person may support one comment only. Liking two or more different comments makes all of that person's likes invalid for this campaign.",
        "summary": {
            "comments": len(comments),
            "raw_likes": sum(row.raw_likes for row in comments),
            "valid_likes": sum(row.valid_likes for row in comments),
            "invalid_likes": sum(row.invalid_likes for row in comments),
            "participating_people": len(user_comments),
            "disqualified_people": len(disqualified),
        },
        "comments": [{
            "id": row.id,
            "facebook_comment_id": row.external_comment_id,
            "message": row.message,
            "author_name": row.author_name,
            "raw_likes": row.raw_likes,
            "valid_likes": row.valid_likes,
            "invalid_likes": row.invalid_likes,
            "synced_at": row.synced_at,
        } for row in comments],
        "disqualified_people": sorted(disqualified, key=lambda row: (row["user_name"] or row["user_id"])),
    }


@router.post("/api/v1/campaigns/{campaign_id}/competition/sync")
def sync_competition(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    if not user.is_tenant_admin and user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Portal staff access required")
    try:
        comments = _fetch_facebook_comments(campaign, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Facebook did not provide usable person-level comment reaction data: {str(exc)[:500]}",
        ) from exc
    summary = _replace_results(db, campaign, comments)
    db.add(AuditLog(actor_user_id=user.id, action="competition.synced", entity_type="campaign", entity_id=str(campaign.id), detail=f"{summary['valid_likes']} valid likes"))
    db.commit()
    return _result_payload(db, campaign)


@router.post("/api/v1/campaigns/{campaign_id}/competition/import")
def import_competition(campaign_id: int, payload: CompetitionImport, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    if not user.is_tenant_admin and user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Portal staff access required")
    _replace_results(db, campaign, payload.comments)
    db.add(AuditLog(actor_user_id=user.id, action="competition.imported", entity_type="campaign", entity_id=str(campaign.id), detail=f"{len(payload.comments)} comments"))
    db.commit()
    return _result_payload(db, campaign)


@router.get("/api/v1/campaigns/{campaign_id}/competition/results")
def competition_results(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    return _result_payload(db, campaign)
