import os
import shutil
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

        paid = client.patch(
            f"/api/v1/payments/{payment_id}",
            headers=auth(admin_token),
            json={"status": "paid", "reference": "TEST-001"},
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "paid"

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
