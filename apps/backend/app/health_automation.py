import os
from datetime import datetime, timezone
from pathlib import Path

import dns.resolver
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .communications import enqueue_notification
from .models import Campaign, CampaignPerformance, CampaignStatus, Payment, PaymentStatus, SystemSetting, Tenant, TenantDomain, User, UserRole
from .realtime import emit_realtime_event
from .tenancy import set_tenant_setting, tenant_setting


def _tenant_admins(db: Session, tenant_id: int) -> list[User]:
    return list(db.scalars(
        select(User).where(
            User.tenant_id == tenant_id,
            User.is_tenant_admin.is_(True),
            User.is_active.is_(True),
        ).order_by(User.id)
    ))


def _notify_health_transition(
    db: Session,
    tenant: Tenant,
    *,
    key: str,
    healthy: bool,
    unhealthy_title: str,
    unhealthy_message: str,
    recovered_title: str,
    recovered_message: str,
) -> bool:
    previous = tenant_setting(db, tenant.id, key)
    current = "healthy" if healthy else "unhealthy"
    changed = previous != current
    set_tenant_setting(db, tenant.id, key, current)
    set_tenant_setting(db, tenant.id, key + ".checked_at", datetime.now(timezone.utc).isoformat())
    if not changed or previous is None:
        return changed

    for admin in _tenant_admins(db, tenant.id):
        enqueue_notification(
            db,
            admin.id,
            "integration_health",
            recovered_title if healthy else unhealthy_title,
            recovered_message if healthy else unhealthy_message,
        )
    emit_realtime_event(
        db,
        "integration.health_changed",
        tenant_id=tenant.id,
        audience="tenant_staff",
        entity_type="tenant",
        entity_id=tenant.id,
        payload={"health_key": key, "status": current},
    )
    return True


def _system_setting(db: Session, key: str) -> str | None:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    return row.value if row else None


def _set_system_setting(db: Session, key: str, value: str | None) -> None:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row:
        row.value = value
        row.encrypted = False
    else:
        db.add(SystemSetting(key=key, value=value, encrypted=False))


def check_backup_freshness(db: Session) -> dict[str, object]:
    root = Path(os.getenv("BACKUP_ROOT", "/data/backups"))
    marker = root / "last-success"
    max_age_hours = max(1, int(os.getenv("BACKUP_MAX_AGE_HOURS", "30")))
    healthy = False
    detail = ""
    age_hours: float | None = None
    try:
        raw = marker.read_text(encoding="utf-8").strip()
        last_success = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - last_success.astimezone(timezone.utc)).total_seconds() / 3600
        db_files = list(root.glob("db-*.dump"))
        media_files = list(root.glob("media-*.tar.gz"))
        healthy = age_hours <= max_age_hours and bool(db_files) and bool(media_files)
        detail = f"Last successful backup {age_hours:.1f}h ago; {len(db_files)} database dumps and {len(media_files)} media archives present."
    except Exception as exc:
        detail = f"Backup marker unavailable or invalid: {str(exc)[:500]}"

    previous = _system_setting(db, "health.backup.status")
    current = "healthy" if healthy else "unhealthy"
    _set_system_setting(db, "health.backup.status", current)
    _set_system_setting(db, "health.backup.detail", detail)
    _set_system_setting(db, "health.backup.checked_at", datetime.now(timezone.utc).isoformat())

    if previous is not None and previous != current:
        admins = list(db.scalars(select(User).where(User.role == UserRole.SUPER_ADMIN, User.is_active.is_(True)).order_by(User.id)))
        for admin in admins:
            enqueue_notification(
                db,
                admin.id,
                "backup_health",
                "Backup health restored" if healthy else "Backup health needs attention",
                detail,
            )
        emit_realtime_event(
            db,
            "backup.health_changed",
            audience="platform_admins",
            entity_type="backup",
            entity_id="primary",
            payload={"status": current, "detail": detail, "age_hours": age_hours},
        )
    db.commit()
    return {"healthy": healthy, "status": current, "detail": detail, "age_hours": age_hours}


def check_meta_integrations(db: Session) -> dict[str, int]:
    checked = healthy = unhealthy = changed = 0
    for tenant in db.scalars(select(Tenant).where(Tenant.active.is_(True)).order_by(Tenant.id)):
        page_id = tenant_setting(db, tenant.id, "meta.page_id")
        token = tenant_setting(db, tenant.id, "meta.page_access_token")
        version = tenant_setting(db, tenant.id, "meta.graph_api_version") or "v24.0"
        if not page_id or not token:
            continue

        checked += 1
        ok = False
        detail = ""
        try:
            response = httpx.get(
                f"https://graph.facebook.com/{version}/{page_id}",
                params={"fields": "id,name", "access_token": token},
                timeout=15.0,
            )
            data = response.json() if response.content else {}
            ok = not response.is_error and str(data.get("id") or "") == str(page_id)
            detail = str(data.get("name") or data.get("error", {}).get("message") or "")
        except Exception as exc:
            detail = str(exc)[:500]

        set_tenant_setting(db, tenant.id, "health.meta.detail", detail[:1000] if detail else None)
        transition = _notify_health_transition(
            db,
            tenant,
            key="health.meta.status",
            healthy=ok,
            unhealthy_title="Facebook connection needs attention",
            unhealthy_message=f"The Meta connection for {tenant.name} is no longer healthy. Publishing, analytics and competition updates may be affected. {detail[:240]}",
            recovered_title="Facebook connection restored",
            recovered_message=f"The Meta connection for {tenant.name} is healthy again.",
        )
        healthy += int(ok)
        unhealthy += int(not ok)
        changed += int(transition)
    db.commit()
    return {"checked": checked, "healthy": healthy, "unhealthy": unhealthy, "changed": changed}


def check_custom_domains(db: Session) -> dict[str, int]:
    checked = healthy = unhealthy = changed = 0
    expected = os.getenv("PORTAL_CNAME_TARGET", "portal.example.com").strip().lower().rstrip(".")
    domains = list(db.scalars(
        select(TenantDomain)
        .where(TenantDomain.status == "verified")
        .order_by(TenantDomain.id)
    ))
    for domain in domains:
        tenant = db.get(Tenant, domain.tenant_id)
        if not tenant:
            continue
        checked += 1
        ok = False
        detail = ""
        try:
            answers = dns.resolver.resolve(domain.hostname, "CNAME")
            targets = {str(answer.target).strip().lower().rstrip(".") for answer in answers}
            ok = expected in targets
            detail = ", ".join(sorted(targets))
        except Exception as exc:
            detail = str(exc)[:500]

        key = f"health.domain.{domain.id}.status"
        set_tenant_setting(db, tenant.id, f"health.domain.{domain.id}.detail", detail[:1000] if detail else None)
        transition = _notify_health_transition(
            db,
            tenant,
            key=key,
            healthy=ok,
            unhealthy_title=f"Custom domain issue: {domain.hostname}",
            unhealthy_message=f"{domain.hostname} is no longer pointing to {expected}. Tenant routing may fail until the CNAME is restored.",
            recovered_title=f"Custom domain restored: {domain.hostname}",
            recovered_message=f"{domain.hostname} is correctly pointing to {expected} again.",
        )
        healthy += int(ok)
        unhealthy += int(not ok)
        changed += int(transition)
    db.commit()
    return {"checked": checked, "healthy": healthy, "unhealthy": unhealthy, "changed": changed}


def send_daily_tenant_digests(db: Session) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    target_hour = int(os.getenv("DAILY_DIGEST_UTC_HOUR", "6")) % 24
    if now.hour != target_hour:
        return {"sent": 0, "skipped_hour": 1}

    today = now.date().isoformat()
    sent = 0
    for tenant in db.scalars(select(Tenant).where(Tenant.active.is_(True)).order_by(Tenant.id)):
        if tenant_setting(db, tenant.id, "digest.daily.last_date") == today:
            continue
        admins = _tenant_admins(db, tenant.id)
        if not admins:
            continue

        campaigns = db.scalar(select(func.count(Campaign.id)).where(Campaign.tenant_id == tenant.id)) or 0
        awaiting = db.scalar(select(func.count(Campaign.id)).where(
            Campaign.tenant_id == tenant.id,
            Campaign.status.in_([CampaignStatus.SUBMITTED, CampaignStatus.IN_REVIEW]),
        )) or 0
        scheduled = db.scalar(select(func.count(Campaign.id)).where(
            Campaign.tenant_id == tenant.id,
            Campaign.status == CampaignStatus.SCHEDULED,
        )) or 0
        published = db.scalar(select(func.count(Campaign.id)).where(
            Campaign.tenant_id == tenant.id,
            Campaign.status == CampaignStatus.PUBLISHED,
        )) or 0
        revenue = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Campaign, Campaign.id == Payment.campaign_id)
            .where(Campaign.tenant_id == tenant.id, Payment.status == PaymentStatus.PAID)
        ) or 0
        performance = db.execute(
            select(
                func.coalesce(func.sum(CampaignPerformance.impressions), 0),
                func.coalesce(func.sum(CampaignPerformance.reach), 0),
                func.coalesce(func.sum(CampaignPerformance.clicks), 0),
                func.coalesce(func.sum(CampaignPerformance.reactions), 0),
            )
            .join(Campaign, Campaign.id == CampaignPerformance.campaign_id)
            .where(Campaign.tenant_id == tenant.id)
        ).one()
        impressions, reach, clicks, reactions = [int(value or 0) for value in performance]

        message = (
            f"Daily summary for {tenant.name}: {campaigns} campaigns, {awaiting} awaiting review, "
            f"{scheduled} scheduled, {published} published, LSL {float(revenue):,.2f} confirmed revenue, "
            f"{reach:,} Facebook reach, {impressions:,} impressions, {clicks:,} clicks and {reactions:,} reactions."
        )
        for admin in admins:
            enqueue_notification(db, admin.id, "daily_digest", "Daily advertising summary", message)
        set_tenant_setting(db, tenant.id, "digest.daily.last_date", today)
        emit_realtime_event(
            db,
            "digest.daily_created",
            tenant_id=tenant.id,
            audience="tenant_staff",
            entity_type="tenant",
            entity_id=tenant.id,
            payload={"date": today, "campaigns": campaigns, "awaiting_review": awaiting, "scheduled": scheduled, "published": published, "revenue": float(revenue), "reach": reach, "impressions": impressions, "clicks": clicks, "reactions": reactions},
        )
        sent += 1
    db.commit()
    return {"sent": sent, "date": today}
