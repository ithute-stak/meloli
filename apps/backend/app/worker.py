import os
import time
from datetime import datetime, timezone

from sqlalchemy import func, select

from .db import SessionLocal
from .communications import deliver_pending, enqueue_notification
from .competition import sync_published_competitions
from .commercial import expire_subscriptions, generate_monthly_corporate_invoices, process_commercial_alerts
from .tenant_billing import process_tenant_subscription_lifecycle
from .meta_service import MetaError, publish_campaign as publish_to_meta
from .models import AuditLog, Campaign, CampaignStatus, PublicationAttempt, PublicationStatus, SystemSetting, Tenant, User, UserRole
from .security import decrypt_secret


def setting(db, key: str) -> str | None:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if not row or not row.value:
        return None
    return decrypt_secret(row.value) if row.encrypted else row.value


def notify_tenant_staff(db, campaign: Campaign, kind: str, title: str, message: str) -> None:
    if not campaign.tenant_id:
        return
    staff = list(db.scalars(
        select(User).where(
            User.tenant_id == campaign.tenant_id,
            User.is_active.is_(True),
            (
                (User.is_tenant_admin.is_(True))
                | (User.role.in_([UserRole.REVIEWER, UserRole.PUBLISHER]))
            ),
        )
    ))
    for user in staff:
        enqueue_notification(db, user.id, kind, title, message)


def run_once() -> int:
    db = SessionLocal()
    processed = 0
    try:
        deliver_pending(db)
        expire_subscriptions(db)
        generate_monthly_corporate_invoices(db)
        process_commercial_alerts(db)
        process_tenant_subscription_lifecycle(db)
        sync_published_competitions(db, min_age_minutes=max(1, int(os.getenv("COMPETITION_SYNC_MINUTES", "10"))), limit=max(1, int(os.getenv("COMPETITION_SYNC_BATCH_SIZE", "10"))))
        due = list(db.scalars(
            select(Campaign)
            .where(
                Campaign.status == CampaignStatus.SCHEDULED,
                Campaign.scheduled_publish_at.is_not(None),
                Campaign.scheduled_publish_at <= datetime.now(timezone.utc),
                Campaign.facebook_post_id.is_(None),
                Campaign.cancelled_at.is_(None),
                Campaign.proof_status == "approved",
            )
            .order_by(Campaign.scheduled_publish_at)
            .limit(int(os.getenv("PUBLISHER_BATCH_SIZE", "20")))
        ))

        for campaign in due:
            from .tenancy import tenant_setting
            tenant = db.get(Tenant, campaign.tenant_id) if campaign.tenant_id else None
            portal_name = tenant.name if tenant else "Advertising Portal"

            # Tenant campaigns must never fall back to another Page's Meta
            # credentials. Global settings are retained only for legacy
            # unscoped campaigns.
            if campaign.tenant_id:
                page_id = tenant_setting(db, campaign.tenant_id, "meta.page_id")
                token = tenant_setting(db, campaign.tenant_id, "meta.page_access_token")
                version = tenant_setting(db, campaign.tenant_id, "meta.graph_api_version") or "v24.0"
            else:
                page_id = setting(db, "meta.page_id")
                token = setting(db, "meta.page_access_token")
                version = setting(db, "meta.graph_api_version")

            previous = db.scalar(select(func.count(PublicationAttempt.id)).where(PublicationAttempt.campaign_id == campaign.id)) or 0
            max_attempts = max(1, int(os.getenv("PUBLISH_RETRY_MAX_ATTEMPTS", "5")))
            retry_delay_minutes = max(1, int(os.getenv("PUBLISH_RETRY_DELAY_MINUTES", "15")))
            last_attempt = db.scalar(
                select(PublicationAttempt)
                .where(PublicationAttempt.campaign_id == campaign.id)
                .order_by(PublicationAttempt.created_at.desc(), PublicationAttempt.id.desc())
            )
            if previous >= max_attempts:
                if campaign.publishing_retry_exhausted_at is None:
                    campaign.publishing_retry_exhausted_at = datetime.now(timezone.utc)
                    message = f"{campaign.title} reached the automatic publishing retry limit on {portal_name}. Resolve the tenant Meta configuration or content issue, then use manual retry."
                    enqueue_notification(db, campaign.advertiser_id, "publishing_failed", "Publishing needs staff attention", message)
                    notify_tenant_staff(db, campaign, "publishing_failed", "Publishing retry limit reached", message)
                    db.add(AuditLog(actor_user_id=None, action="campaign.publish_retry_exhausted", entity_type="campaign", entity_id=str(campaign.id), detail=f"{previous} attempts"))
                    db.commit()
                continue
            if last_attempt and last_attempt.status == PublicationStatus.FAILED:
                last_time = last_attempt.updated_at or last_attempt.created_at
                last_time = last_time.replace(tzinfo=timezone.utc) if last_time.tzinfo is None else last_time
                if (datetime.now(timezone.utc) - last_time).total_seconds() < retry_delay_minutes * 60:
                    continue

            attempt = PublicationAttempt(
                campaign_id=campaign.id,
                attempt_number=int(previous) + 1,
                status=PublicationStatus.PENDING,
            )
            db.add(attempt)
            db.flush()
            try:
                if not page_id or not token or not version:
                    raise MetaError("This tenant's Meta Page publishing configuration is incomplete")
                result = publish_to_meta(
                    page_id=page_id,
                    access_token=token,
                    version=version,
                    message=campaign.caption,
                    media_url=campaign.media_url,
                    destination_url=campaign.destination_url,
                    media_items=[(item.url, item.content_type) for item in campaign.media_items],
                )
                attempt.status = PublicationStatus.PUBLISHED
                attempt.external_post_id = result.post_id
                attempt.external_post_url = result.post_url
                campaign.facebook_post_id = result.post_id
                campaign.facebook_post_url = result.post_url
                campaign.published_at = datetime.now(timezone.utc)
                campaign.status = CampaignStatus.PUBLISHED
                campaign.publishing_retry_exhausted_at = None
                enqueue_notification(
                    db,
                    campaign.advertiser_id,
                    "published",
                    "Your advert is live",
                    f"{campaign.title} has been published automatically on the {portal_name} Facebook Page.",
                )
                from .corporate_api import emit_corporate_webhook
                emit_corporate_webhook(db, campaign, "campaign.published")
                processed += 1
            except MetaError as exc:
                attempt.status = PublicationStatus.FAILED
                attempt.error_message = str(exc)[:4000]
                message = f"{campaign.title} could not be published at the scheduled time on {portal_name}. Automatic retry {int(previous) + 1} of {max_attempts} failed: {str(exc)[:240]}"
                enqueue_notification(
                    db,
                    campaign.advertiser_id,
                    "publishing_delay",
                    "Publishing delayed",
                    message,
                )
                notify_tenant_staff(
                    db,
                    campaign,
                    "publishing_delay",
                    "Scheduled publishing failed",
                    message,
                )
            db.commit()
        return processed
    finally:
        db.close()


def main() -> None:
    interval = max(15, int(os.getenv("PUBLISHER_POLL_SECONDS", "60")))
    print(f"[Meloli Worker] scheduled publisher started; interval={interval}s", flush=True)
    while True:
        try:
            count = run_once()
            if count:
                print(f"[Meloli Worker] published {count} due campaign(s)", flush=True)
        except Exception as exc:
            print(f"[Meloli Worker] cycle failed: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
