import os
import time
from datetime import datetime, timezone

from sqlalchemy import func, select

from .db import SessionLocal
from .communications import deliver_pending, enqueue_notification
from .commercial import expire_subscriptions, generate_monthly_corporate_invoices, process_commercial_alerts
from .meta_service import MetaError, publish_campaign as publish_to_meta
from .models import Campaign, CampaignStatus, PublicationAttempt, PublicationStatus, SystemSetting, Tenant
from .security import decrypt_secret


def setting(db, key: str) -> str | None:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if not row or not row.value:
        return None
    return decrypt_secret(row.value) if row.encrypted else row.value


def run_once() -> int:
    db = SessionLocal()
    processed = 0
    try:
        deliver_pending(db)
        expire_subscriptions(db)
        generate_monthly_corporate_invoices(db)
        process_commercial_alerts(db)
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
            page_id = tenant_setting(db, campaign.tenant_id, "meta.page_id") if campaign.tenant_id else None
            token = tenant_setting(db, campaign.tenant_id, "meta.page_access_token") if campaign.tenant_id else None
            version = tenant_setting(db, campaign.tenant_id, "meta.graph_api_version") if campaign.tenant_id else None
            page_id = page_id or setting(db, "meta.page_id")
            token = token or setting(db, "meta.page_access_token")
            version = version or setting(db, "meta.graph_api_version")
            tenant = db.get(Tenant, campaign.tenant_id) if campaign.tenant_id else None
            portal_name = tenant.name if tenant else "Meloli Airwaves"
            if not page_id or not token or not version:
                continue

            previous = db.scalar(select(func.count(PublicationAttempt.id)).where(PublicationAttempt.campaign_id == campaign.id)) or 0
            attempt = PublicationAttempt(
                campaign_id=campaign.id,
                attempt_number=int(previous) + 1,
                status=PublicationStatus.PENDING,
            )
            db.add(attempt)
            db.flush()
            try:
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
                enqueue_notification(
                    db,
                    campaign.advertiser_id,
                    "publishing_delay",
                    "Publishing delayed",
                    f"{campaign.title} could not be published at the scheduled time. {portal_name} staff have been alerted and will retry.",
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
