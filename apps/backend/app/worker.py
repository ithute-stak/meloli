import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .automation import run_job_if_due
from .communications import deliver_pending, enqueue_notification
from .commercial import expire_subscriptions, generate_monthly_corporate_invoices, process_commercial_alerts
from .competition import close_due_competitions, sync_published_competitions
from .db import SessionLocal
from .meta_service import MetaError, publish_campaign as publish_to_meta
from .models import AuditLog, Campaign, CampaignStatus, Payment, PaymentStatus, PublicationAttempt, PublicationStatus, SystemSetting, Tenant, User, UserRole
from .realtime import cleanup_realtime_events, emit_realtime_event
from .security import decrypt_secret
from .tenant_billing import process_tenant_subscription_lifecycle
from .meta_webhooks import process_meta_webhook_events
from .health_automation import check_custom_domains, check_meta_integrations, send_daily_tenant_digests
from .presence import cleanup_review_presence


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


def _reminder_sent_since(db, campaign_id: int, action: str, since: datetime) -> bool:
    return bool(db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.entity_type == "campaign",
            AuditLog.entity_id == str(campaign_id),
            AuditLog.action == action,
            AuditLog.created_at >= since,
        )
    ))


def process_campaign_reminders(db) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    sent = payment = review = proof = schedule = 0

    campaigns = list(db.scalars(
        select(Campaign)
        .where(Campaign.cancelled_at.is_(None))
        .order_by(Campaign.created_at)
        .limit(500)
    ))
    for campaign in campaigns:
        created = campaign.created_at.replace(tzinfo=timezone.utc) if campaign.created_at.tzinfo is None else campaign.created_at
        updated = campaign.updated_at.replace(tzinfo=timezone.utc) if campaign.updated_at.tzinfo is None else campaign.updated_at
        daily_cutoff = now - timedelta(hours=20)

        if campaign.status == CampaignStatus.PAYMENT_PENDING and now - created >= timedelta(hours=int(os.getenv("PAYMENT_REMINDER_HOURS", "24"))):
            if not _reminder_sent_since(db, campaign.id, "automation.payment_reminder", daily_cutoff):
                enqueue_notification(
                    db,
                    campaign.advertiser_id,
                    "payment_reminder",
                    f"Payment needed for {campaign.title}",
                    "Your campaign is waiting for payment confirmation. Complete or submit payment so editorial review can begin.",
                )
                db.add(AuditLog(actor_user_id=None, action="automation.payment_reminder", entity_type="campaign", entity_id=str(campaign.id)))
                payment += 1; sent += 1

        if campaign.status in {CampaignStatus.SUBMITTED, CampaignStatus.IN_REVIEW} and now - updated >= timedelta(hours=int(os.getenv("REVIEW_SLA_HOURS", "4"))):
            if not _reminder_sent_since(db, campaign.id, "automation.review_sla_alert", daily_cutoff):
                message = f"{campaign.title} has been waiting in editorial review beyond the configured SLA."
                notify_tenant_staff(db, campaign, "review_sla", "Campaign review needs attention", message)
                db.add(AuditLog(actor_user_id=None, action="automation.review_sla_alert", entity_type="campaign", entity_id=str(campaign.id), detail=message))
                review += 1; sent += 1

        if campaign.proof_status == "pending_advertiser" and campaign.proof_requested_at:
            proof_requested = campaign.proof_requested_at.replace(tzinfo=timezone.utc) if campaign.proof_requested_at.tzinfo is None else campaign.proof_requested_at
            if now - proof_requested >= timedelta(hours=int(os.getenv("PROOF_REMINDER_HOURS", "24"))) and not _reminder_sent_since(db, campaign.id, "automation.proof_reminder", daily_cutoff):
                enqueue_notification(
                    db,
                    campaign.advertiser_id,
                    "proof_reminder",
                    f"Final proof waiting: {campaign.title}",
                    "Your advert passed editorial review and is waiting for your final proof approval before it can be scheduled or published.",
                )
                db.add(AuditLog(actor_user_id=None, action="automation.proof_reminder", entity_type="campaign", entity_id=str(campaign.id)))
                proof += 1; sent += 1

        if campaign.status == CampaignStatus.SCHEDULED and campaign.scheduled_publish_at:
            publish_at = campaign.scheduled_publish_at.replace(tzinfo=timezone.utc) if campaign.scheduled_publish_at.tzinfo is None else campaign.scheduled_publish_at
            lead = timedelta(minutes=int(os.getenv("PUBLISHING_REMINDER_MINUTES", "60")))
            if now <= publish_at <= now + lead and not _reminder_sent_since(db, campaign.id, "automation.publish_upcoming", publish_at - timedelta(hours=24)):
                message = f"{campaign.title} is scheduled to publish at {publish_at.strftime('%d %b %Y %H:%M UTC')}."
                notify_tenant_staff(db, campaign, "publishing_upcoming", "Scheduled publication approaching", message)
                db.add(AuditLog(actor_user_id=None, action="automation.publish_upcoming", entity_type="campaign", entity_id=str(campaign.id), detail=message))
                schedule += 1; sent += 1

    db.commit()
    return {"sent": sent, "payment": payment, "review_sla": review, "proof": proof, "publishing_upcoming": schedule}


def process_scheduled_publishing(db) -> dict[str, int]:
    processed = failed = exhausted = 0
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
                if campaign.tenant_id:
                    emit_realtime_event(
                        db, "campaign.publish_retry_exhausted", tenant_id=campaign.tenant_id, audience="tenant_staff",
                        entity_type="campaign", entity_id=campaign.id,
                        payload={"campaign_id": campaign.id, "title": campaign.title, "attempts": int(previous)},
                    )
                db.commit()
                exhausted += 1
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
            if campaign.tenant_id:
                emit_realtime_event(
                    db, "campaign.published", tenant_id=campaign.tenant_id, audience="tenant_staff",
                    entity_type="campaign", entity_id=campaign.id,
                    payload={"campaign_id": campaign.id, "title": campaign.title, "facebook_post_url": result.post_url, "automatic": True},
                )
            processed += 1
        except MetaError as exc:
            attempt.status = PublicationStatus.FAILED
            attempt.error_message = str(exc)[:4000]
            message = f"{campaign.title} could not be published at the scheduled time on {portal_name}. Automatic retry {int(previous) + 1} of {max_attempts} failed: {str(exc)[:240]}"
            enqueue_notification(db, campaign.advertiser_id, "publishing_delay", "Publishing delayed", message)
            notify_tenant_staff(db, campaign, "publishing_delay", "Scheduled publishing failed", message)
            if campaign.tenant_id:
                emit_realtime_event(
                    db, "campaign.publish_failed", tenant_id=campaign.tenant_id, audience="tenant_staff",
                    entity_type="campaign", entity_id=campaign.id,
                    payload={"campaign_id": campaign.id, "title": campaign.title, "attempt": int(previous) + 1, "max_attempts": max_attempts, "error": str(exc)[:500]},
                )
            failed += 1
        db.commit()

    return {"published": processed, "failed": failed, "retry_exhausted": exhausted, "eligible": len(due)}


def run_once() -> dict[str, object]:
    db = SessionLocal()
    ran: dict[str, object] = {}
    try:
        jobs = [
            ("notification_delivery", max(10, int(os.getenv("NOTIFICATION_DELIVERY_SECONDS", "30"))), lambda s: deliver_pending(s)),
            ("meta_webhook_processing", max(10, int(os.getenv("META_WEBHOOK_PROCESS_SECONDS", "20"))), lambda s: process_meta_webhook_events(s, limit=max(1, int(os.getenv("META_WEBHOOK_BATCH_SIZE", "50"))))),
            ("campaign_reminders", max(60, int(os.getenv("CAMPAIGN_REMINDER_CHECK_SECONDS", "300"))), process_campaign_reminders),
            ("competition_closing", max(30, int(os.getenv("COMPETITION_CLOSE_CHECK_SECONDS", "60"))), lambda s: close_due_competitions(s, limit=max(1, int(os.getenv("COMPETITION_CLOSE_BATCH_SIZE", "20"))))),
            ("advertiser_subscription_expiry", max(300, int(os.getenv("ADVERTISER_SUBSCRIPTION_CHECK_SECONDS", "3600"))), lambda s: expire_subscriptions(s)),
            ("corporate_monthly_invoices", max(900, int(os.getenv("CORPORATE_INVOICE_CHECK_SECONDS", "21600"))), lambda s: generate_monthly_corporate_invoices(s)),
            ("commercial_alerts", max(300, int(os.getenv("COMMERCIAL_ALERT_CHECK_SECONDS", "3600"))), lambda s: process_commercial_alerts(s)),
            ("tenant_subscription_lifecycle", max(300, int(os.getenv("TENANT_SUBSCRIPTION_CHECK_SECONDS", "3600"))), lambda s: process_tenant_subscription_lifecycle(s)),
            ("meta_health_check", max(300, int(os.getenv("META_HEALTH_CHECK_SECONDS", "1800"))), check_meta_integrations),
            ("domain_health_check", max(900, int(os.getenv("DOMAIN_HEALTH_CHECK_SECONDS", "3600"))), check_custom_domains),
            ("daily_tenant_digest", max(900, int(os.getenv("DAILY_DIGEST_CHECK_SECONDS", "3600"))), send_daily_tenant_digests),
            ("review_presence_cleanup", max(30, int(os.getenv("REVIEW_PRESENCE_CLEANUP_SECONDS", "60"))), cleanup_review_presence),
            ("realtime_event_cleanup", max(300, int(os.getenv("REALTIME_CLEANUP_SECONDS", "3600"))), lambda s: {"deleted": cleanup_realtime_events(s, retention_hours=max(1, int(os.getenv("REALTIME_EVENT_RETENTION_HOURS", "48"))))}),
            ("competition_sync", max(60, int(os.getenv("COMPETITION_SYNC_MINUTES", "10")) * 60), lambda s: {"synced": sync_published_competitions(s, min_age_minutes=max(1, int(os.getenv("COMPETITION_SYNC_MINUTES", "10"))), limit=max(1, int(os.getenv("COMPETITION_SYNC_BATCH_SIZE", "10"))))}),
            ("scheduled_publishing", max(15, int(os.getenv("PUBLISHER_POLL_SECONDS", "60"))), process_scheduled_publishing),
        ]
        for key, interval, fn in jobs:
            executed, result = run_job_if_due(db, key, interval, fn)
            if executed:
                ran[key] = result
        return ran
    finally:
        db.close()


def main() -> None:
    tick = max(5, int(os.getenv("AUTOMATION_TICK_SECONDS", "10")))
    print(f"[Meloli Automation] scheduler started; tick={tick}s", flush=True)
    while True:
        try:
            ran = run_once()
            if ran:
                print(f"[Meloli Automation] completed jobs: {', '.join(ran.keys())}", flush=True)
        except Exception as exc:
            print(f"[Meloli Automation] scheduler cycle failed: {exc}", flush=True)
        time.sleep(tick)


if __name__ == "__main__":
    main()
