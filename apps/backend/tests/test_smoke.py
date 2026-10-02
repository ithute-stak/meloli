import hashlib
import hmac
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyotp

TEST_DIR = Path(__file__).parent
TEST_DB = TEST_DIR / "test_meloli.db"
TEST_MEDIA = TEST_DIR / "test_media"
if TEST_DB.exists():
    TEST_DB.unlink()
if TEST_MEDIA.exists():
    shutil.rmtree(TEST_MEDIA)
TEST_MEDIA.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["MEDIA_ROOT"] = str(TEST_MEDIA)
os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["SETTINGS_ENCRYPTION_KEY"] = "test-settings-secret"
os.environ["SUPER_ADMIN_EMAIL"] = "admin@example.com"
os.environ["SUPER_ADMIN_PASSWORD"] = "StrongTestPassword123!"
os.environ["SUPER_ADMIN_NAME"] = "Test Admin"
os.environ["FRONTEND_PUBLIC_URL"] = "http://localhost:3000"

from fastapi.testclient import TestClient  # noqa: E402
from app.asgi import app  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Campaign, MetaWebhookEvent, Tenant, TenantSubscription  # noqa: E402
from app.tenant_billing import process_tenant_subscription_lifecycle  # noqa: E402
from app.automation import run_job_if_due  # noqa: E402
from app import competition as competition_module  # noqa: E402
from app.competition import ImportedComment, ImportedReaction, close_due_competitions  # noqa: E402
from app.meta_webhooks import process_meta_webhook_events  # noqa: E402
from app import health_automation as health_module  # noqa: E402


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_advertising_workflow_smoke():
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["version"] == "1.0.0"

        register = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Advertiser Test",
                "business_name": "Test Business",
                "email": "advertiser@example.com",
                "phone": "+26650000000",
                "password": "AdvertiserPassword123!",
            },
        )
        assert register.status_code == 201, register.text
        advertiser_token = register.json()["access_token"]

        profile = client.patch(
            "/api/v1/profile",
            headers=auth(advertiser_token),
            json={"full_name": "Advertiser Updated", "business_name": "Test Business", "phone": "+26651111111"},
        )
        assert profile.status_code == 200, profile.text
        assert profile.json()["full_name"] == "Advertiser Updated"

        packages = client.get("/api/v1/packages")
        assert packages.status_code == 200
        assert len(packages.json()) >= 1
        package_code = packages.json()[0]["code"]

        campaign = client.post(
            "/api/v1/campaigns",
            headers=auth(advertiser_token),
            json={"title": "Test advert", "caption": "A test advert caption", "package_code": package_code, "media_items": [{"url": "/media/test-one.jpg", "content_type": "image/jpeg"}, {"url": "/media/test-two.jpg", "content_type": "image/jpeg"}]},
        )
        assert campaign.status_code == 201, campaign.text
        campaign_id = campaign.json()["id"]
        assert campaign.json()["status"] == "payment_pending"
        assert len(campaign.json()["media_items"]) == 2
        assert campaign.json()["media_items"][0]["url"] == "/media/test-one.jpg"

        quote = client.get(f"/api/v1/campaigns/{campaign_id}/quotation.pdf", headers=auth(advertiser_token))
        assert quote.status_code == 200
        assert quote.content.startswith(b"%PDF")

        duplicate = client.post(f"/api/v1/campaigns/{campaign_id}/duplicate", headers=auth(advertiser_token))
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["source_campaign_id"] == campaign_id
        duplicate_campaign_id = duplicate.json()["id"]
        duplicated_rows = client.get("/api/v1/campaigns", headers=auth(advertiser_token))
        assert duplicated_rows.status_code == 200
        duplicated_campaign = next(row for row in duplicated_rows.json() if row["id"] == duplicate_campaign_id)
        assert len(duplicated_campaign["media_items"]) == 2

        ticket = client.post(
            "/api/v1/support/tickets",
            headers=auth(advertiser_token),
            json={"subject": "Please help", "message": "I need help with this campaign", "campaign_id": campaign_id},
        )
        assert ticket.status_code == 201, ticket.text
        ticket_id = ticket.json()["id"]

        payment = client.post(
            f"/api/v1/campaigns/{campaign_id}/payments",
            headers=auth(advertiser_token),
            json={"method": "manual", "reference": "TEST-001"},
        )
        assert payment.status_code == 201, payment.text
        payment_id = payment.json()["id"]

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "StrongTestPassword123!"},
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_token = admin_login.json()["access_token"]

        referral_partner = client.post(
            "/api/v1/admin/referral-partners",
            headers=auth(admin_token),
            json={"name": "Agency Partner", "code": "AGENCY10", "commission_percent": 10, "contact_email": "partner@example.com", "active": True},
        )
        assert referral_partner.status_code == 201, referral_partner.text

        referred_register = client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Referred Advertiser",
                "business_name": "Referral Test",
                "email": "referred@example.com",
                "phone": "+26652222222",
                "password": "ReferredPassword123!",
                "referral_code": "AGENCY10",
            },
        )
        assert referred_register.status_code == 201, referred_register.text
        referral_metrics = client.get("/api/v1/admin/referral-partners", headers=auth(admin_token))
        assert referral_metrics.status_code == 200, referral_metrics.text
        partner_metrics = next(row for row in referral_metrics.json() if row["code"] == "AGENCY10")
        assert partner_metrics["referred_advertisers"] == 1

        promo = client.post(
            "/api/v1/admin/promos",
            headers=auth(admin_token),
            json={"code": "WELCOME10", "percent_off": 10, "fixed_off": 0, "max_uses": 10, "active": True},
        )
        assert promo.status_code == 201, promo.text

        discounted = client.post(
            f"/api/v1/campaigns/{duplicate_campaign_id}/payments",
            headers=auth(advertiser_token),
            json={"method": "bank_transfer", "reference": "DISC-001", "promo_code": "WELCOME10"},
        )
        assert discounted.status_code == 201, discounted.text
        assert discounted.json()["amount"] < payment.json()["amount"]

        corporate = client.put(
            f"/api/v1/admin/advertisers/{register.json()['user']['id']}/corporate",
            headers=auth(admin_token),
            json={"credit_limit": 2000, "billing_cycle_day": 1, "active": True},
        )
        assert corporate.status_code == 200, corporate.text
        assert corporate.json()["credit_limit"] == 2000

        api_client = client.post(
            "/api/v1/admin/corporate-api/clients",
            headers=auth(admin_token),
            json={"user_id": register.json()["user"]["id"], "name": "Smoke Integration", "webhook_url": None},
        )
        assert api_client.status_code == 201, api_client.text
        corporate_api_key = api_client.json()["api_key"]
        corporate_api_client_id = api_client.json()["id"]

        api_campaign = client.post(
            "/api/v1/corporate-api/campaigns",
            headers={"X-API-Key": corporate_api_key},
            json={"title": "API submitted advert", "caption": "Created through corporate API", "package_code": package_code, "media_items": []},
        )
        assert api_campaign.status_code == 201, api_campaign.text
        assert api_campaign.json()["status"] == "submitted"

        api_campaigns = client.get("/api/v1/corporate-api/campaigns", headers={"X-API-Key": corporate_api_key})
        assert api_campaigns.status_code == 200, api_campaigns.text
        assert any(row["id"] == api_campaign.json()["id"] for row in api_campaigns.json())

        plan = client.post(
            "/api/v1/admin/subscription-plans",
            headers=auth(admin_token),
            json={"code": "BUSINESS4", "name": "Business Four", "description": "Four monthly adverts", "monthly_price": 1500, "included_posts": 4, "active": True},
        )
        assert plan.status_code == 201, plan.text
        assigned = client.post(
            "/api/v1/admin/subscriptions",
            headers=auth(admin_token),
            json={"user_id": register.json()["user"]["id"], "plan_id": plan.json()["id"], "months": 1},
        )
        assert assigned.status_code == 201, assigned.text
        commercial = client.get("/api/v1/commercial/my-account", headers=auth(advertiser_token))
        assert commercial.status_code == 200
        assert commercial.json()["subscription"]["remaining_posts"] == 4

        realtime_ticket = client.post("/api/v1/realtime/ticket", headers=auth(advertiser_token))
        assert realtime_ticket.status_code == 200, realtime_ticket.text
        assert realtime_ticket.json()["expires_in"] == 300
        with client.websocket_connect(
            "/api/v1/realtime/ws?ticket=" + realtime_ticket.json()["ticket"] + "&after=0"
        ) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            paid = client.patch(
                f"/api/v1/payments/{payment_id}",
                headers=auth(admin_token),
                json={"status": "paid", "reference": "TEST-001"},
            )
            assert paid.status_code == 200, paid.text
            assert paid.json()["status"] == "paid"
            realtime_message = None
            for _ in range(30):
                candidate = websocket.receive_json()
                if candidate.get("type") == "event" and candidate.get("topic") == "notification.created":
                    realtime_message = candidate
                    break
            assert realtime_message is not None
            assert realtime_message["payload"]["kind"] == "payment"

        db = SessionLocal()
        try:
            executed, job_result = run_job_if_due(db, "smoke_automation", 60, lambda _: {"ok": True})
            assert executed is True
            assert job_result == {"ok": True}
        finally:
            db.close()
        automation_jobs = client.get("/api/v1/admin/automation/jobs", headers=auth(admin_token))
        assert automation_jobs.status_code == 200, automation_jobs.text
        smoke_job = next(row for row in automation_jobs.json() if row["job_key"] == "smoke_automation")
        assert smoke_job["last_status"] == "success"
        assert smoke_job["run_count"] == 1
        assert smoke_job["stalled"] is False

        queue_job = client.post(
            "/api/v1/admin/automation/jobs/smoke_automation/run-now",
            headers=auth(admin_token),
        )
        assert queue_job.status_code == 200, queue_job.text
        assert queue_job.json()["status"] == "queued"
        assert queue_job.json()["due"] is True

        queued_jobs = client.get("/api/v1/admin/automation/jobs", headers=auth(admin_token))
        assert queued_jobs.status_code == 200, queued_jobs.text
        queued_smoke_job = next(row for row in queued_jobs.json() if row["job_key"] == "smoke_automation")
        assert queued_smoke_job["last_status"] == "queued"
        assert queued_smoke_job["due"] is True

        missing_job = client.post(
            "/api/v1/admin/automation/jobs/does-not-exist/run-now",
            headers=auth(admin_token),
        )
        assert missing_job.status_code == 404

        campaigns = client.get("/api/v1/campaigns", headers=auth(admin_token))
        assert campaigns.status_code == 200
        current = next(c for c in campaigns.json() if c["id"] == campaign_id)
        assert current["status"] == "submitted"

        approval_without_checklist = client.patch(
            f"/api/v1/campaigns/{campaign_id}/decision",
            headers=auth(admin_token),
            json={"status": "approved", "reviewer_note": "Approved for publication"},
        )
        assert approval_without_checklist.status_code == 409

        checklist = client.put(
            f"/api/v1/campaigns/{campaign_id}/review-checklist",
            headers=auth(admin_token),
            json={
                "content_accuracy_checked": True,
                "media_rights_checked": True,
                "contact_details_checked": True,
                "policy_checked": True,
                "notes": "Smoke test moderation completed",
            },
        )
        assert checklist.status_code == 200, checklist.text
        assert checklist.json()["completed"] is True

        approved = client.patch(
            f"/api/v1/campaigns/{campaign_id}/decision",
            headers=auth(admin_token),
            json={"status": "approved", "reviewer_note": "Approved for publication"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        assert approved.json()["proof_status"] == "pending_advertiser"
        proof = client.post(
            f"/api/v1/campaigns/{campaign_id}/proof/decision",
            headers=auth(advertiser_token),
            json={"decision": "approved", "feedback": None},
        )
        assert proof.status_code == 200, proof.text
        assert proof.json()["proof_status"] == "approved"

        receipt = client.get(f"/api/v1/payments/{payment_id}/receipt.pdf", headers=auth(advertiser_token))
        assert receipt.status_code == 200, receipt.text
        assert receipt.headers["content-type"] == "application/pdf"
        assert receipt.content.startswith(b"%PDF")

        invoice = client.get(f"/api/v1/campaigns/{campaign_id}/invoice.pdf", headers=auth(advertiser_token))
        assert invoice.status_code == 200
        assert invoice.content.startswith(b"%PDF")

        notifications = client.get("/api/v1/notifications", headers=auth(advertiser_token))
        assert notifications.status_code == 200
        assert len(notifications.json()) >= 2

        summary = client.get("/api/v1/admin/reports/summary", headers=auth(admin_token))
        assert summary.status_code == 200
        assert summary.json()["campaigns"] >= 1
        assert summary.json()["paid_payments"] >= 1

        forecast = client.get("/api/v1/admin/growth/forecast", headers=auth(admin_token))
        assert forecast.status_code == 200, forecast.text
        assert forecast.json()["forecast_next_30_days"] >= 0

        revoke_api = client.patch(
            f"/api/v1/admin/corporate-api/clients/{corporate_api_client_id}/state",
            headers=auth(admin_token),
            json={"active": False},
        )
        assert revoke_api.status_code == 200, revoke_api.text
        assert revoke_api.json()["active"] is False
        revoked_api_use = client.get("/api/v1/corporate-api/campaigns", headers={"X-API-Key": corporate_api_key})
        assert revoked_api_use.status_code == 401

        advertiser_performance = client.get("/api/v1/advertiser/performance/summary", headers=auth(advertiser_token))
        assert advertiser_performance.status_code == 200
        assert advertiser_performance.json()["campaigns_published"] == 0

        admin_performance = client.get("/api/v1/admin/performance/summary", headers=auth(admin_token))
        assert admin_performance.status_code == 200

        advertisers = client.get("/api/v1/admin/advertisers", headers=auth(admin_token))
        assert advertisers.status_code == 200
        primary_advertiser = next(row for row in advertisers.json() if row["email"] == "advertiser@example.com")
        assert primary_advertiser["confirmed_spend"] > 0

        staff = client.post(
            "/api/v1/admin/staff",
            headers=auth(admin_token),
            json={"full_name": "Review User", "email": "reviewer@example.com", "password": "ReviewPassword123!", "role": "reviewer"},
        )
        assert staff.status_code == 201, staff.text

        ticket_reply = client.patch(
            f"/api/v1/support/tickets/{ticket_id}",
            headers=auth(admin_token),
            json={"status": "resolved", "staff_reply": "Your request has been resolved."},
        )
        assert ticket_reply.status_code == 200, ticket_reply.text
        assert ticket_reply.json()["status"] == "resolved"

        audit = client.get("/api/v1/admin/audit", headers=auth(admin_token))
        assert audit.status_code == 200
        assert len(audit.json()) >= 1

        ops_health = client.get("/api/v1/admin/system-health", headers=auth(admin_token))
        assert ops_health.status_code == 200
        assert ops_health.json()["database"] == "ok"

        communications = client.put(
            "/api/v1/system/communications",
            headers=auth(admin_token),
            json={
                "email_enabled": False,
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "notifications@example.com",
                "from_email": "notifications@example.com",
                "smtp_use_tls": True,
                "webhook_enabled": False,
                "webhook_url": "https://example.com/webhook"
            },
        )
        assert communications.status_code == 200, communications.text
        assert communications.json()["email_enabled"] is False
        assert communications.json()["webhook_enabled"] is False

        corporate_campaign = client.post(
            "/api/v1/campaigns",
            headers=auth(advertiser_token),
            json={"title": "Corporate credit advert", "caption": "Corporate billing test advert", "package_code": package_code},
        )
        assert corporate_campaign.status_code == 201, corporate_campaign.text
        corporate_campaign_id = corporate_campaign.json()["id"]
        corporate_payment = client.post(
            f"/api/v1/campaigns/{corporate_campaign_id}/payments",
            headers=auth(advertiser_token),
            json={"method": "corporate_credit"},
        )
        assert corporate_payment.status_code == 201, corporate_payment.text
        assert corporate_payment.json()["status"] == "paid"
        corporate_payment_id = corporate_payment.json()["id"]

        invoices = client.get("/api/v1/admin/corporate-invoices", headers=auth(admin_token))
        assert invoices.status_code == 200, invoices.text
        assert any(row["user_id"] == register.json()["user"]["id"] for row in invoices.json())

        corp_cancel = client.post(
            f"/api/v1/campaigns/{corporate_campaign_id}/cancel",
            headers=auth(advertiser_token),
            json={"reason": "Corporate advert cancelled for credit note test"},
        )
        assert corp_cancel.status_code == 200, corp_cancel.text
        corp_refund_id = corp_cancel.json()["refund_request_id"]
        assert corp_refund_id is not None

        corp_refund = client.post(
            f"/api/v1/admin/refunds/{corp_refund_id}/decision",
            headers=auth(admin_token),
            json={"status": "approved", "staff_note": "Approved for credit note test"},
        )
        assert corp_refund.status_code == 200, corp_refund.text

        credit_notes = client.get("/api/v1/admin/credit-notes", headers=auth(admin_token))
        assert credit_notes.status_code == 200, credit_notes.text
        credit_note = next(row for row in credit_notes.json() if row["payment_id"] == corporate_payment_id)
        assert credit_note["invoice_id"] is not None
        assert credit_note["amount"] == corporate_payment.json()["amount"]
        credit_pdf = client.get(
            f"/api/v1/admin/credit-notes/{credit_note['id']}/pdf",
            headers=auth(admin_token),
        )
        assert credit_pdf.status_code == 200, credit_pdf.text
        assert credit_pdf.content.startswith(b"%PDF")

        # Multi-tenant isolation and one-person/one-comment competition voting.
        tenant_a = client.post(
            "/api/v1/tenants/register",
            json={
                "page_name": "Page Alpha",
                "desired_slug": "page-alpha",
                "facebook_page_id": "page-alpha-facebook-id",
                "owner_name": "Alpha Owner",
                "owner_email": "alpha.owner@example.com",
                "owner_phone": "+26650000001",
                "password": "AlphaOwnerPassword123!",
            },
        )
        assert tenant_a.status_code == 201, tenant_a.text
        assert tenant_a.json()["slug"] == "page-alpha"
        assert "/p/page-alpha" in tenant_a.json()["generated_url"]

        tenant_plans = client.get("/api/v1/admin/tenant-plans", headers=auth(admin_token))
        assert tenant_plans.status_code == 200, tenant_plans.text
        business_plan = next(row for row in tenant_plans.json() if row["code"] == "BUSINESS")
        platform_summary = client.get("/api/v1/admin/platform/summary", headers=auth(admin_token))
        assert platform_summary.status_code == 200, platform_summary.text
        assert platform_summary.json()["tenants"] >= 2
        assert platform_summary.json()["trialing_subscriptions"] >= 1

        tenant_b = client.post(
            "/api/v1/tenants/register",
            json={
                "page_name": "Page Beta",
                "desired_slug": "page-beta",
                "owner_name": "Beta Owner",
                "owner_email": "beta.owner@example.com",
                "owner_phone": "+26650000002",
                "password": "BetaOwnerPassword123!",
            },
        )
        assert tenant_b.status_code == 201, tenant_b.text

        duplicate_page = client.post(
            "/api/v1/tenants/register",
            json={
                "page_name": "Page Alpha Duplicate",
                "desired_slug": "page-alpha-copy",
                "facebook_page_id": "page-alpha-facebook-id",
                "owner_name": "Duplicate Owner",
                "owner_email": "duplicate.owner@example.com",
                "password": "DuplicateOwnerPassword123!",
            },
        )
        assert duplicate_page.status_code == 409
        assert "already registered" in duplicate_page.json()["detail"].lower()

        resolved_a = client.get("/api/v1/tenants/resolve?slug=page-alpha")
        assert resolved_a.status_code == 200, resolved_a.text
        assert resolved_a.json()["name"] == "Page Alpha"

        alpha_login = client.post(
            "/api/v1/auth/login",
            json={"email": "alpha.owner@example.com", "password": "AlphaOwnerPassword123!"},
        )
        beta_login = client.post(
            "/api/v1/auth/login",
            json={"email": "beta.owner@example.com", "password": "BetaOwnerPassword123!"},
        )
        assert alpha_login.status_code == 200, alpha_login.text
        assert beta_login.status_code == 200, beta_login.text
        alpha_token = alpha_login.json()["access_token"]
        beta_token = beta_login.json()["access_token"]
        assert alpha_login.json()["user"]["is_tenant_admin"] is True
        assert alpha_login.json()["user"]["tenant_id"] != beta_login.json()["user"]["tenant_id"]

        alpha_subscription = client.put(
            f"/api/v1/admin/tenants/{tenant_a.json()['id']}/subscription",
            headers=auth(admin_token),
            json={"plan_id": business_plan["id"], "billing_period": "monthly", "status": "active"},
        )
        assert alpha_subscription.status_code == 200, alpha_subscription.text
        assert alpha_subscription.json()["plan"]["code"] == "BUSINESS"
        assert alpha_subscription.json()["plan"]["custom_domains"] is True
        assert alpha_subscription.json()["plan"]["competition_certification"] is True

        alpha_meta = client.put(
            "/api/v1/tenant-admin/meta",
            headers=auth(alpha_token),
            json={
                "app_id": "alpha-meta-app",
                "app_secret": "alpha-meta-secret",
                "page_id": "page-alpha-facebook-id",
                "page_access_token": "alpha-page-token",
                "webhook_verify_token": "alpha-webhook-verify",
                "graph_api_version": "v24.0",
            },
        )
        assert alpha_meta.status_code == 200, alpha_meta.text
        assert alpha_meta.json()["webhook_verify_token_configured"] is True
        assert alpha_meta.json()["webhook_callback_url"].endswith("/api/v1/meta/webhook")

        verify_webhook = client.get(
            "/api/v1/meta/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "alpha-webhook-verify",
                "hub.challenge": "alpha-challenge",
            },
        )
        assert verify_webhook.status_code == 200, verify_webhook.text
        assert verify_webhook.text == "alpha-challenge"

        webhook_payload = {
            "object": "page",
            "entry": [{
                "id": "page-alpha-facebook-id",
                "time": 1760000000,
                "changes": [{"field": "feed", "value": {"item": "comment", "verb": "add", "post_id": "unknown-post"}}],
            }],
        }
        webhook_body = json.dumps(webhook_payload, separators=(",", ":")).encode("utf-8")
        signature = "sha256=" + hmac.new(b"alpha-meta-secret", webhook_body, hashlib.sha256).hexdigest()
        received_webhook = client.post(
            "/api/v1/meta/webhook",
            content=webhook_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )
        assert received_webhook.status_code == 200, received_webhook.text
        assert received_webhook.json()["accepted"] == 1
        duplicate_webhook = client.post(
            "/api/v1/meta/webhook",
            content=webhook_body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )
        assert duplicate_webhook.status_code == 200, duplicate_webhook.text
        assert duplicate_webhook.json()["accepted"] == 0
        db = SessionLocal()
        try:
            assert db.query(MetaWebhookEvent).filter(MetaWebhookEvent.tenant_id == tenant_a.json()["id"]).count() >= 1
        finally:
            db.close()

        # Failed webhook processing moves to a dead-letter state after the
        # retry budget and can be explicitly requeued by a tenant admin.
        db = SessionLocal()
        try:
            poison = MetaWebhookEvent(
                tenant_id=tenant_a.json()["id"],
                page_id="page-alpha-facebook-id",
                object_type="page",
                payload_sha256="f" * 64,
                payload_json="{invalid-json",
                status="failed",
                attempts=4,
            )
            db.add(poison)
            db.commit()
            poison_id = poison.id
            webhook_process = process_meta_webhook_events(db, limit=50)
            assert webhook_process["failed"] >= 1
            db.expire_all()
            poison = db.get(MetaWebhookEvent, poison_id)
            assert poison.status == "dead_letter"
            assert poison.attempts == 5
        finally:
            db.close()

        webhook_events = client.get("/api/v1/admin/meta/webhook-events", headers=auth(alpha_token))
        assert webhook_events.status_code == 200, webhook_events.text
        assert any(row["id"] == poison_id and row["status"] == "dead_letter" for row in webhook_events.json())
        webhook_retry = client.post(
            f"/api/v1/admin/meta/webhook-events/{poison_id}/retry",
            headers=auth(alpha_token),
        )
        assert webhook_retry.status_code == 200, webhook_retry.text
        assert webhook_retry.json()["status"] == "pending"
        assert webhook_retry.json()["attempts"] == 0

        # Meta health monitoring records the health state exposed to the tenant
        # dashboard without needing a real network call in tests.
        original_meta_get = health_module.httpx.get
        class HealthyMetaResponse:
            is_error = False
            content = b'{"id":"page-alpha-facebook-id","name":"Page Alpha"}'
            def json(self):
                return {"id": "page-alpha-facebook-id", "name": "Page Alpha"}
        health_module.httpx.get = lambda *args, **kwargs: HealthyMetaResponse()
        db = SessionLocal()
        try:
            meta_health = health_module.check_meta_integrations(db)
            assert meta_health["checked"] >= 1
            assert meta_health["healthy"] >= 1
        finally:
            health_module.httpx.get = original_meta_get
            db.close()
        alpha_meta_health = client.get("/api/v1/tenant-admin/meta", headers=auth(alpha_token))
        assert alpha_meta_health.status_code == 200, alpha_meta_health.text
        assert alpha_meta_health.json()["health_status"] == "healthy"

        backup_root = TEST_DIR / "test_backups"
        if backup_root.exists():
            shutil.rmtree(backup_root)
        backup_root.mkdir(parents=True, exist_ok=True)
        (backup_root / "last-success").write_text(datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        (backup_root / "db-test.dump").write_bytes(b"database")
        (backup_root / "media-test.tar.gz").write_bytes(b"media")
        previous_backup_root = os.environ.get("BACKUP_ROOT")
        os.environ["BACKUP_ROOT"] = str(backup_root)
        db = SessionLocal()
        try:
            backup_health = health_module.check_backup_freshness(db)
            assert backup_health["healthy"] is True
            assert backup_health["status"] == "healthy"
            db.commit()
        finally:
            db.close()
            if previous_backup_root is None:
                os.environ.pop("BACKUP_ROOT", None)
            else:
                os.environ["BACKUP_ROOT"] = previous_backup_root
            shutil.rmtree(backup_root)

        platform_health = client.get("/api/v1/admin/platform-health", headers=auth(admin_token))
        assert platform_health.status_code == 200, platform_health.text
        assert platform_health.json()["backup"]["status"] == "healthy"
        assert "database dumps" in platform_health.json()["backup"]["detail"]

        alpha_campaign = client.post(
            "/api/v1/campaigns",
            headers=auth(alpha_token),
            json={
                "title": "Comment voting competition",
                "caption": "Vote by liking one comment only",
                "package_code": package_code,
                "engagement_mode": "competition_one_comment",
                "competition_closes_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
                "competition_auto_certify": True,
            },
        )
        assert alpha_campaign.status_code == 201, alpha_campaign.text
        competition_id = alpha_campaign.json()["id"]
        assert alpha_campaign.json()["engagement_mode"] == "competition_one_comment"
        assert alpha_campaign.json()["competition_closes_at"] is not None
        assert alpha_campaign.json()["competition_auto_certify"] is True

        alpha_presence = client.post(
            f"/api/v1/campaigns/{alpha_campaign.json()['id']}/presence/heartbeat",
            headers=auth(alpha_token),
        )
        assert alpha_presence.status_code == 200, alpha_presence.text
        alpha_presence_list = client.get(
            f"/api/v1/campaigns/{alpha_campaign.json()['id']}/presence",
            headers=auth(alpha_token),
        )
        assert alpha_presence_list.status_code == 200, alpha_presence_list.text
        assert any(row["full_name"] == "Alpha Owner" for row in alpha_presence_list.json())
        beta_cross_presence = client.post(
            f"/api/v1/campaigns/{alpha_campaign.json()['id']}/presence/heartbeat",
            headers=auth(beta_token),
        )
        assert beta_cross_presence.status_code == 403
        alpha_leave_presence = client.delete(
            f"/api/v1/campaigns/{alpha_campaign.json()['id']}/presence",
            headers=auth(alpha_token),
        )
        assert alpha_leave_presence.status_code == 200, alpha_leave_presence.text
        alpha_presence_after_leave = client.get(
            f"/api/v1/campaigns/{alpha_campaign.json()['id']}/presence",
            headers=auth(alpha_token),
        )
        assert alpha_presence_after_leave.status_code == 200
        assert alpha_presence_after_leave.json() == []

        imported_votes = client.post(
            f"/api/v1/campaigns/{competition_id}/competition/import",
            headers=auth(alpha_token),
            json={
                "comments": [
                    {
                        "comment_id": "comment-1",
                        "message": "Entry One",
                        "author_name": "Contestant One",
                        "reactions": [
                            {"user_id": "theko", "user_name": "Koetlisi Theko"},
                            {"user_id": "mpho", "user_name": "Mpho"},
                        ],
                    },
                    {
                        "comment_id": "comment-3",
                        "message": "Entry Three",
                        "author_name": "Contestant Three",
                        "reactions": [
                            {"user_id": "theko", "user_name": "Koetlisi Theko"},
                            {"user_id": "palesa", "user_name": "Palesa"},
                        ],
                    },
                ]
            },
        )
        assert imported_votes.status_code == 200, imported_votes.text
        vote_data = imported_votes.json()
        assert vote_data["summary"]["raw_likes"] == 4
        assert vote_data["summary"]["valid_likes"] == 2
        assert vote_data["summary"]["invalid_likes"] == 2
        assert vote_data["summary"]["disqualified_people"] == 1
        theko = next(row for row in vote_data["disqualified_people"] if row["user_name"] == "Koetlisi Theko")
        assert theko["comments_liked"] == 2
        assert all(row["valid_likes"] == 1 for row in vote_data["comments"])

        # A duplicate copy of the same Facebook comment must not inflate totals.
        # If Koetlisi removes the second like, the remaining single-comment vote
        # becomes valid again on the next full sync/import.
        refreshed_votes = client.post(
            f"/api/v1/campaigns/{competition_id}/competition/import",
            headers=auth(alpha_token),
            json={
                "comments": [
                    {
                        "comment_id": "comment-1",
                        "message": "Entry One",
                        "author_name": "Contestant One",
                        "reactions": [
                            {"user_id": "theko", "user_name": "Koetlisi Theko"},
                            {"user_id": "mpho", "user_name": "Mpho"},
                        ],
                    },
                    {
                        "comment_id": "comment-1",
                        "message": "Entry One",
                        "author_name": "Contestant One",
                        "reactions": [
                            {"user_id": "theko", "user_name": "Koetlisi Theko"},
                        ],
                    },
                    {
                        "comment_id": "comment-3",
                        "message": "Entry Three",
                        "author_name": "Contestant Three",
                        "reactions": [
                            {"user_id": "palesa", "user_name": "Palesa"},
                        ],
                    },
                ]
            },
        )
        assert refreshed_votes.status_code == 200, refreshed_votes.text
        refreshed = refreshed_votes.json()
        assert refreshed["summary"]["comments"] == 2
        assert refreshed["summary"]["raw_likes"] == 3
        assert refreshed["summary"]["valid_likes"] == 3
        assert refreshed["summary"]["invalid_likes"] == 0
        assert refreshed["summary"]["disqualified_people"] == 0
        assert refreshed["disqualified_people"] == []
        entry_one = next(row for row in refreshed["comments"] if row["facebook_comment_id"] == "comment-1")
        assert entry_one["raw_likes"] == 2
        assert entry_one["valid_likes"] == 2

        # A second due competition is closed automatically: final reactions
        # are synchronized, frozen, and certified under the tenant owner.
        auto_campaign = client.post(
            "/api/v1/campaigns",
            headers=auth(alpha_token),
            json={
                "title": "Automatic closing competition",
                "caption": "Automatic close test",
                "package_code": package_code,
                "engagement_mode": "competition_one_comment",
                "competition_closes_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                "competition_auto_certify": True,
            },
        )
        assert auto_campaign.status_code == 201, auto_campaign.text
        auto_competition_id = auto_campaign.json()["id"]
        db = SessionLocal()
        original_fetch = competition_module._fetch_facebook_comments
        try:
            row = db.get(Campaign, auto_competition_id)
            row.facebook_post_id = "auto-facebook-post"
            row.status = "published"
            db.commit()
            competition_module._fetch_facebook_comments = lambda campaign, session: [
                ImportedComment(
                    comment_id="auto-comment-1",
                    message="Automatic Entry",
                    author_name="Automatic Contestant",
                    reactions=[
                        ImportedReaction(user_id="auto-voter-1", user_name="Auto Voter One"),
                        ImportedReaction(user_id="auto-voter-2", user_name="Auto Voter Two"),
                    ],
                )
            ]
            auto_result = close_due_competitions(db)
            assert auto_result["closed"] >= 1
            assert auto_result["certified"] >= 1
            db.expire_all()
            row = db.get(Campaign, auto_competition_id)
            assert row.competition_closed_at is not None
        finally:
            competition_module._fetch_facebook_comments = original_fetch
            db.close()
        auto_results = client.get(
            f"/api/v1/campaigns/{auto_competition_id}/competition/results",
            headers=auth(alpha_token),
        )
        assert auto_results.status_code == 200, auto_results.text
        assert auto_results.json()["summary"]["valid_likes"] == 2
        assert auto_results.json()["certification"]["frozen"] is True

        certified = client.post(
            f"/api/v1/campaigns/{competition_id}/competition/certify",
            headers=auth(alpha_token),
        )
        assert certified.status_code == 201, certified.text
        assert certified.json()["frozen"] is True
        assert len(certified.json()["snapshot_sha256"]) == 64

        frozen_import = client.post(
            f"/api/v1/campaigns/{competition_id}/competition/import",
            headers=auth(alpha_token),
            json={"comments": []},
        )
        assert frozen_import.status_code == 409
        assert "frozen" in frozen_import.json()["detail"].lower()

        certificate_pdf = client.get(
            f"/api/v1/campaigns/{competition_id}/competition/certificate.pdf",
            headers=auth(alpha_token),
        )
        assert certificate_pdf.status_code == 200, certificate_pdf.text
        assert certificate_pdf.headers["content-type"] == "application/pdf"
        assert certificate_pdf.content.startswith(b"%PDF")

        certified_results = client.get(
            f"/api/v1/campaigns/{competition_id}/competition/results",
            headers=auth(alpha_token),
        )
        assert certified_results.status_code == 200
        assert certified_results.json()["certification"]["frozen"] is True
        assert certified_results.json()["certification"]["snapshot_sha256"] == certified.json()["snapshot_sha256"]

        cross_tenant_results = client.get(
            f"/api/v1/campaigns/{competition_id}/competition/results",
            headers=auth(beta_token),
        )
        assert cross_tenant_results.status_code == 403

        starter_domain = client.post(
            "/api/v1/tenant-admin/domains",
            headers=auth(beta_token),
            json={"hostname": "ads.page-beta.example"},
        )
        assert starter_domain.status_code == 403
        assert "does not include custom domains" in starter_domain.json()["detail"].lower()

        domain_request = client.post(
            "/api/v1/tenant-admin/domains",
            headers=auth(alpha_token),
            json={"hostname": "ads.page-alpha.example"},
        )
        assert domain_request.status_code == 201, domain_request.text
        assert domain_request.json()["status"] == "pending"
        assert domain_request.json()["verification_token"].startswith("meloli-")

        staff_member = client.post(
            "/api/v1/tenant-admin/staff",
            headers=auth(alpha_token),
            json={
                "full_name": "Alpha Reviewer",
                "email": "alpha.reviewer@example.com",
                "password": "AlphaReviewerPassword123!",
                "role": "reviewer",
            },
        )
        assert staff_member.status_code == 201, staff_member.text
        assert staff_member.json()["role"] == "reviewer"
        onboarding = client.get("/api/v1/tenant-admin/onboarding", headers=auth(alpha_token))
        assert onboarding.status_code == 200, onboarding.text
        assert onboarding.json()["subscription"]["plan"]["code"] == "BUSINESS"
        assert onboarding.json()["percent"] >= 50

        # LoanHub-inspired tenant subscription checkout: create an invoice,
        # keep the payment pending until platform confirmation, then activate
        # the tenant subscription and issue branded PDF documents.
        starter_plan = next(row for row in tenant_plans.json() if row["code"] == "STARTER")
        beta_checkout = client.post(
            "/api/v1/tenant-admin/billing/checkout",
            headers=auth(beta_token),
            json={
                "plan_id": starter_plan["id"],
                "billing_period": "monthly",
                "payment_method": "bank_transfer",
                "payment_reference": "BETA-BANK-001",
            },
        )
        assert beta_checkout.status_code == 201, beta_checkout.text
        beta_invoice = beta_checkout.json()
        assert beta_invoice["status"] == "issued"
        assert beta_invoice["payment"]["status"] == "pending"
        beta_invoice_pdf = client.get(
            f"/api/v1/tenant-billing/invoices/{beta_invoice['id']}.pdf",
            headers=auth(beta_token),
        )
        assert beta_invoice_pdf.status_code == 200, beta_invoice_pdf.text
        assert beta_invoice_pdf.content.startswith(b"%PDF")

        beta_confirm = client.post(
            f"/api/v1/admin/tenant-billing/payments/{beta_invoice['payment']['id']}/confirm",
            headers=auth(admin_token),
            json={"status": "paid", "reference": "BETA-BANK-001"},
        )
        assert beta_confirm.status_code == 200, beta_confirm.text
        assert beta_confirm.json()["status"] == "paid"
        assert beta_confirm.json()["payment"]["status"] == "paid"
        assert len(beta_confirm.json()["payment"]["verification_code"]) == 20

        beta_receipt_pdf = client.get(
            f"/api/v1/tenant-billing/payments/{beta_invoice['payment']['id']}/receipt.pdf",
            headers=auth(beta_token),
        )
        assert beta_receipt_pdf.status_code == 200, beta_receipt_pdf.text
        assert beta_receipt_pdf.content.startswith(b"%PDF")

        beta_billing = client.get("/api/v1/tenant-admin/billing", headers=auth(beta_token))
        assert beta_billing.status_code == 200, beta_billing.text
        assert any(row["invoice_number"] == beta_invoice["invoice_number"] and row["status"] == "paid" for row in beta_billing.json())

        # Lifecycle processor marks expired subscriptions past due, then
        # suspends the tenant when the configured grace period has elapsed.
        db = SessionLocal()
        try:
            subscription = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_b.json()["id"]).first()
            assert subscription is not None
            subscription.current_period_end = datetime.now(timezone.utc) - timedelta(days=8)
            subscription.status = "active"
            tenant_row = db.get(Tenant, tenant_b.json()["id"])
            tenant_row.active = True
            db.commit()
            lifecycle = process_tenant_subscription_lifecycle(db)
            assert lifecycle["suspended"] >= 1
            db.refresh(subscription)
            db.refresh(tenant_row)
            assert subscription.status == "suspended"
            assert tenant_row.active is False
        finally:
            db.close()

        beta_resolve_after_suspend = client.get("/api/v1/tenants/resolve?slug=page-beta")
        assert beta_resolve_after_suspend.status_code == 404

        # Confirming a later payment reactivates the tenant.
        beta_reactivation = client.post(
            "/api/v1/tenant-admin/billing/checkout",
            headers=auth(beta_token),
            json={
                "plan_id": starter_plan["id"],
                "billing_period": "monthly",
                "payment_method": "bank_transfer",
                "payment_reference": "BETA-BANK-002",
            },
        )
        assert beta_reactivation.status_code == 201, beta_reactivation.text
        reactivation_payment_id = beta_reactivation.json()["payment"]["id"]
        reactivated = client.post(
            f"/api/v1/admin/tenant-billing/payments/{reactivation_payment_id}/confirm",
            headers=auth(admin_token),
            json={"status": "paid", "reference": "BETA-BANK-002"},
        )
        assert reactivated.status_code == 200, reactivated.text
        beta_resolve_restored = client.get("/api/v1/tenants/resolve?slug=page-beta")
        assert beta_resolve_restored.status_code == 200, beta_resolve_restored.text

        two_factor_setup = client.post("/api/v1/profile/2fa/setup", headers=auth(admin_token))
        assert two_factor_setup.status_code == 200, two_factor_setup.text
        otp_secret = two_factor_setup.json()["secret"]
        otp_code = pyotp.TOTP(otp_secret).now()
        two_factor_enable = client.post("/api/v1/profile/2fa/enable", headers=auth(admin_token), json={"code": otp_code})
        assert two_factor_enable.status_code == 200, two_factor_enable.text
        assert two_factor_enable.json()["enabled"] is True

        admin_login_without_otp = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "StrongTestPassword123!"},
        )
        assert admin_login_without_otp.status_code == 401

        admin_login_with_otp = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "StrongTestPassword123!", "otp_code": pyotp.TOTP(otp_secret).now()},
        )
        assert admin_login_with_otp.status_code == 200, admin_login_with_otp.text

        # Account recovery never reveals whether an email exists.
        recovery = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "advertiser@example.com"},
        )
        assert recovery.status_code == 200
        assert "password reset instructions" in recovery.json()["message"].lower()

        # Session records are visible and can be revoked individually.
        sessions = client.get("/api/v1/profile/sessions", headers=auth(advertiser_token))
        assert sessions.status_code == 200, sessions.text
        assert any(row["active"] for row in sessions.json())

        # Cancelling a paid, unpublished campaign creates a refund case.
        cancelled = client.post(
            f"/api/v1/campaigns/{campaign_id}/cancel",
            headers=auth(advertiser_token),
            json={"reason": "Campaign is no longer required"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["refund_request_id"] is not None
        refund_id = cancelled.json()["refund_request_id"]

        refunds = client.get("/api/v1/refunds", headers=auth(advertiser_token))
        assert refunds.status_code == 200, refunds.text
        assert any(row["id"] == refund_id and row["status"] == "requested" for row in refunds.json())

        refund_decision = client.post(
            f"/api/v1/admin/refunds/{refund_id}/decision",
            headers=auth(admin_login_with_otp.json()["access_token"]),
            json={"status": "approved", "staff_note": "Approved in lifecycle smoke test"},
        )
        assert refund_decision.status_code == 200, refund_decision.text
        assert refund_decision.json()["status"] == "approved"

        # Sign-out-all invalidates the token used to request it.
        revoked = client.post("/api/v1/profile/logout-all", headers=auth(advertiser_token))
        assert revoked.status_code == 200, revoked.text
        after_revoke = client.get("/api/v1/auth/me", headers=auth(advertiser_token))
        assert after_revoke.status_code == 401
