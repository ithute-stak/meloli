from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .branding import LIGHT, MUTED, NAVY, draw_footer, draw_header, tenant_brand
from .communications import enqueue_notification
from .db import get_db
from .models import AuditLog, Campaign, CompetitionCertification, CompetitionComment, CompetitionReaction, User, UserRole
from .security import validate_token_user
from .tenancy import current_tenant_subscription, tenant_setting
from .realtime import emit_realtime_event

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
    if user.role != UserRole.SUPER_ADMIN:
        if not user.tenant_id or campaign.tenant_id != user.tenant_id:
            raise HTTPException(status_code=403, detail="Campaign belongs to another portal")
    if user.role == UserRole.ADVERTISER and not user.is_tenant_admin and campaign.advertiser_id != user.id:
        raise HTTPException(status_code=403, detail="You cannot access this campaign")
    return campaign


def require_competition(campaign: Campaign) -> None:
    if campaign.engagement_mode != "competition_one_comment":
        raise HTTPException(status_code=409, detail="This campaign is not using one-person/one-comment competition mode")


def existing_certification(db: Session, campaign_id: int) -> CompetitionCertification | None:
    return db.scalar(select(CompetitionCertification).where(CompetitionCertification.campaign_id == campaign_id))


def require_mutable_competition(db: Session, campaign: Campaign) -> None:
    certification = existing_certification(db, campaign.id)
    if certification:
        raise HTTPException(
            status_code=409,
            detail=f"Competition results were certified at {certification.certified_at.isoformat()} and are frozen",
        )


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

    # Meta paging and manual imports can occasionally contain the same comment
    # more than once. Canonicalise by external comment id and merge reactions so
    # a duplicate payload row can never inflate raw or valid totals.
    canonical: dict[str, ImportedComment] = {}
    for comment in comments:
        existing = canonical.get(comment.comment_id)
        if existing is None:
            canonical[comment.comment_id] = ImportedComment(
                comment_id=comment.comment_id,
                message=comment.message,
                author_name=comment.author_name,
                reactions=list(comment.reactions),
            )
            continue
        merged = {reaction.user_id: reaction for reaction in existing.reactions}
        for reaction in comment.reactions:
            merged[reaction.user_id] = reaction
        existing.reactions = list(merged.values())
        existing.message = comment.message or existing.message
        existing.author_name = comment.author_name or existing.author_name

    canonical_comments = list(canonical.values())
    seen_by_user: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str | None] = {}
    deduped: dict[str, dict[str, ImportedReaction]] = {}
    for comment in canonical_comments:
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

    for item in canonical_comments:
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
    certification = existing_certification(db, campaign.id)
    return {
        "campaign_id": campaign.id,
        "title": campaign.title,
        "certification": None if not certification else {
            "id": certification.id,
            "certified_at": certification.certified_at,
            "certified_by_user_id": certification.certified_by_user_id,
            "snapshot_sha256": certification.snapshot_sha256,
            "frozen": True,
        },
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


def sync_competition_campaign(db: Session, campaign: Campaign, automatic: bool = True) -> dict | None:
    require_competition(campaign)
    if existing_certification(db, campaign.id):
        return None
    comments = _fetch_facebook_comments(campaign, db)
    summary = _replace_results(db, campaign, comments)
    db.add(AuditLog(
        actor_user_id=None,
        action="competition.auto_synced" if automatic else "competition.synced",
        entity_type="campaign",
        entity_id=str(campaign.id),
        detail=f"{summary['valid_likes']} valid likes",
    ))
    if campaign.tenant_id:
        emit_realtime_event(
            db,
            "competition.results_updated",
            tenant_id=campaign.tenant_id,
            audience="tenant_all",
            entity_type="campaign",
            entity_id=campaign.id,
            payload={
                "campaign_id": campaign.id,
                "valid_likes": summary["valid_likes"],
                "invalid_likes": summary["invalid_likes"],
                "automatic": automatic,
            },
        )
    return summary


def certify_competition_snapshot(
    db: Session,
    campaign: Campaign,
    certified_by_user_id: int | None = None,
    *,
    require_plan: bool = True,
) -> CompetitionCertification:
    existing = existing_certification(db, campaign.id)
    if existing:
        return existing
    if not campaign.tenant_id:
        raise RuntimeError("Campaign is not attached to a tenant")
    subscription, plan = current_tenant_subscription(db, campaign.tenant_id)
    if require_plan and (not subscription or not plan or not plan.competition_certification):
        raise RuntimeError("Tenant plan does not include competition certification")
    result = _result_payload(db, campaign)
    if result["summary"]["comments"] == 0:
        raise RuntimeError("Sync competition votes before certifying results")
    result.pop("certification", None)
    snapshot = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    certification = CompetitionCertification(
        campaign_id=campaign.id,
        snapshot_json=snapshot,
        snapshot_sha256=digest,
        certified_by_user_id=certified_by_user_id,
        certified_at=datetime.now(timezone.utc),
    )
    db.add(certification)
    db.flush()
    campaign.competition_closed_at = campaign.competition_closed_at or datetime.now(timezone.utc)
    db.add(AuditLog(
        actor_user_id=certified_by_user_id,
        action="competition.certified",
        entity_type="campaign",
        entity_id=str(campaign.id),
        detail=digest,
    ))
    emit_realtime_event(
        db,
        "competition.certified",
        tenant_id=campaign.tenant_id,
        audience="tenant_all",
        entity_type="campaign",
        entity_id=campaign.id,
        payload={"campaign_id": campaign.id, "snapshot_sha256": digest, "certified_at": certification.certified_at},
    )
    return certification


def close_due_competitions(db: Session, limit: int = 20) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    campaigns = list(db.scalars(
        select(Campaign)
        .where(
            Campaign.engagement_mode == "competition_one_comment",
            Campaign.competition_closes_at.is_not(None),
            Campaign.competition_closes_at <= now,
            Campaign.competition_closed_at.is_(None),
            Campaign.facebook_post_id.is_not(None),
            Campaign.cancelled_at.is_(None),
        )
        .order_by(Campaign.competition_closes_at)
        .limit(limit)
    ))
    closed = certified = failed = 0
    for campaign in campaigns:
        try:
            sync_competition_campaign(db, campaign, automatic=True)
            campaign.competition_closed_at = now
            db.add(AuditLog(actor_user_id=None, action="competition.closed_automatically", entity_type="campaign", entity_id=str(campaign.id), detail=str(campaign.competition_closes_at)))
            if campaign.competition_auto_certify:
                certify_competition_snapshot(db, campaign, certified_by_user_id=None, require_plan=True)
                certified += 1
            enqueue_notification(
                db,
                campaign.advertiser_id,
                "competition_closed",
                f"{campaign.title} competition closed",
                "The configured closing time has been reached. Final Facebook reactions were synchronized and the result is now frozen." if campaign.competition_auto_certify else "The configured closing time has been reached and final Facebook reactions were synchronized.",
            )
            if campaign.tenant_id:
                emit_realtime_event(
                    db,
                    "competition.closed",
                    tenant_id=campaign.tenant_id,
                    audience="tenant_all",
                    entity_type="campaign",
                    entity_id=campaign.id,
                    payload={"campaign_id": campaign.id, "auto_certified": bool(campaign.competition_auto_certify)},
                )
            db.commit()
            closed += 1
        except Exception as exc:
            db.rollback()
            db.add(AuditLog(actor_user_id=None, action="competition.auto_close_failed", entity_type="campaign", entity_id=str(campaign.id), detail=str(exc)[:1000]))
            db.commit()
            failed += 1
    return {"closed": closed, "certified": certified, "failed": failed}


def sync_published_competitions(db: Session, min_age_minutes: int = 10, limit: int = 10) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - max(1, min_age_minutes) * 60
    campaigns = list(db.scalars(
        select(Campaign)
        .where(
            Campaign.engagement_mode == "competition_one_comment",
            Campaign.facebook_post_id.is_not(None),
            Campaign.cancelled_at.is_(None),
        )
        .order_by(Campaign.updated_at.desc())
        .limit(limit)
    ))
    synced = 0
    for campaign in campaigns:
        latest = db.scalar(
            select(func.max(CompetitionComment.synced_at))
            .where(CompetitionComment.campaign_id == campaign.id)
        )
        latest_ts = None
        if latest:
            latest = latest.replace(tzinfo=timezone.utc) if latest.tzinfo is None else latest
            latest_ts = latest.timestamp()
        if latest_ts is not None and latest_ts > cutoff:
            continue
        if existing_certification(db, campaign.id):
            continue
        try:
            if sync_competition_campaign(db, campaign, automatic=True) is not None:
                db.commit()
                synced += 1
        except Exception as exc:
            db.rollback()
            db.add(AuditLog(actor_user_id=None, action="competition.auto_sync_failed", entity_type="campaign", entity_id=str(campaign.id), detail=str(exc)[:1000]))
            db.commit()
    return synced


@router.post("/api/v1/campaigns/{campaign_id}/competition/sync")
def sync_competition(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    require_mutable_competition(db, campaign)
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
    if campaign.tenant_id:
        emit_realtime_event(
            db, "competition.results_updated", tenant_id=campaign.tenant_id, audience="tenant_all",
            entity_type="campaign", entity_id=campaign.id,
            payload={"campaign_id": campaign.id, "valid_likes": summary["valid_likes"], "invalid_likes": summary["invalid_likes"], "automatic": False},
        )
    db.commit()
    return _result_payload(db, campaign)


@router.post("/api/v1/campaigns/{campaign_id}/competition/import")
def import_competition(campaign_id: int, payload: CompetitionImport, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    require_mutable_competition(db, campaign)
    if not user.is_tenant_admin and user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Portal staff access required")
    _replace_results(db, campaign, payload.comments)
    db.add(AuditLog(actor_user_id=user.id, action="competition.imported", entity_type="campaign", entity_id=str(campaign.id), detail=f"{len(payload.comments)} comments"))
    if campaign.tenant_id:
        result = _result_payload(db, campaign)
        emit_realtime_event(
            db, "competition.results_updated", tenant_id=campaign.tenant_id, audience="tenant_all",
            entity_type="campaign", entity_id=campaign.id,
            payload={"campaign_id": campaign.id, "valid_likes": result["summary"]["valid_likes"], "invalid_likes": result["summary"]["invalid_likes"]},
        )
    db.commit()
    return _result_payload(db, campaign)


@router.get("/api/v1/campaigns/{campaign_id}/competition/results")
def competition_results(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    return _result_payload(db, campaign)


@router.post("/api/v1/campaigns/{campaign_id}/competition/certify", status_code=201)
def certify_competition(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    if not user.is_tenant_admin and user.role not in {UserRole.REVIEWER, UserRole.PUBLISHER, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Portal staff access required")
    try:
        certification = certify_competition_snapshot(
            db,
            campaign,
            certified_by_user_id=user.id,
            require_plan=user.role != UserRole.SUPER_ADMIN,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=403 if "plan" in str(exc).lower() else 409, detail=str(exc)) from exc
    digest = certification.snapshot_sha256
    db.commit()
    return {
        "id": certification.id,
        "campaign_id": campaign.id,
        "certified_at": certification.certified_at,
        "snapshot_sha256": digest,
        "frozen": True,
    }


@router.get("/api/v1/campaigns/{campaign_id}/competition/certificate.pdf")
def competition_certificate_pdf(campaign_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    campaign = campaign_for_user(db, campaign_id, user)
    require_competition(campaign)
    certification = existing_certification(db, campaign.id)
    if not certification:
        raise HTTPException(status_code=404, detail="Competition results have not been certified")
    snapshot = json.loads(certification.snapshot_json)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    brand_name, _, _ = tenant_brand(db, campaign.tenant_id)
    document_no = f"COMP-{campaign.id:06d}-{certification.id:04d}"
    pdf.setTitle(f"{brand_name} competition result certificate {document_no}")
    draw_header(pdf, db, "Competition result certificate", document_no, "CERTIFIED", tenant_id=campaign.tenant_id)

    y = height - 155
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(55, y, snapshot.get("title") or campaign.title)
    y -= 24
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(MUTED)
    pdf.drawString(55, y, f"Certified: {str(certification.certified_at)[:19]} UTC")
    y -= 15
    pdf.drawString(55, y, f"SHA-256: {certification.snapshot_sha256}")
    y -= 28

    summary = snapshot.get("summary") or {}
    pdf.setFillColor(LIGHT)
    pdf.roundRect(50, y - 72, width - 100, 72, 12, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10)
    metrics = [
        ("Comments", summary.get("comments", 0)),
        ("Raw likes", summary.get("raw_likes", 0)),
        ("Valid likes", summary.get("valid_likes", 0)),
        ("Invalid likes", summary.get("invalid_likes", 0)),
        ("Disqualified people", summary.get("disqualified_people", 0)),
    ]
    x = 64
    for label, value in metrics:
        pdf.setFont("Helvetica", 7)
        pdf.drawString(x, y - 22, label)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(x, y - 43, str(value))
        x += 94
    y -= 98

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(55, y, "Certified leaderboard")
    y -= 18
    for index, row in enumerate(snapshot.get("comments") or [], start=1):
        if y < 100:
            draw_footer(pdf, db, campaign.tenant_id)
            pdf.showPage()
            draw_header(pdf, db, "Competition result certificate", document_no, "CERTIFIED", tenant_id=campaign.tenant_id)
            y = height - 155
        author = (row.get("author_name") or "Facebook comment")[:46]
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(55, y, f"#{index}  {author}")
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(width - 55, y, f"Valid {row.get('valid_likes', 0)}   Raw {row.get('raw_likes', 0)}   Invalid {row.get('invalid_likes', 0)}")
        y -= 16

    y -= 8
    if y < 90:
        draw_footer(pdf, db, campaign.tenant_id)
        pdf.showPage()
        draw_header(pdf, db, "Competition result certificate", document_no, "CERTIFIED", tenant_id=campaign.tenant_id)
        y = height - 155
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(MUTED)
    pdf.drawString(55, y, "Rule: one person may support one comment only; multiple different comment likes are all invalid.")
    y -= 14
    pdf.drawString(55, y, "This certificate is generated from the frozen result snapshot identified by the SHA-256 fingerprint above.")
    draw_footer(pdf, db, campaign.tenant_id)
    pdf.save()
    return Response(
        buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{document_no}.pdf"'},
    )
