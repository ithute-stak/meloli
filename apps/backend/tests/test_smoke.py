import os
import shutil
from pathlib import Path

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
            json={"title": "Test advert", "caption": "A test advert caption", "package_code": package_code},
        )
        assert campaign.status_code == 201, campaign.text
        campaign_id = campaign.json()["id"]
        assert campaign.json()["status"] == "payment_pending"

        quote = client.get(f"/api/v1/campaigns/{campaign_id}/quotation.pdf", headers=auth(advertiser_token))
        assert quote.status_code == 200
        assert quote.content.startswith(b"%PDF")

        duplicate = client.post(f"/api/v1/campaigns/{campaign_id}/duplicate", headers=auth(advertiser_token))
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["source_campaign_id"] == campaign_id

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

        approved = client.patch(
            f"/api/v1/campaigns/{campaign_id}/decision",
            headers=auth(admin_token),
            json={"status": "approved", "reviewer_note": "Approved for publication"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

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

        advertiser_performance = client.get("/api/v1/advertiser/performance/summary", headers=auth(advertiser_token))
        assert advertiser_performance.status_code == 200
        assert advertiser_performance.json()["campaigns_published"] == 0

        admin_performance = client.get("/api/v1/admin/performance/summary", headers=auth(admin_token))
        assert admin_performance.status_code == 200

        advertisers = client.get("/api/v1/admin/advertisers", headers=auth(admin_token))
        assert advertisers.status_code == 200
        assert advertisers.json()[0]["confirmed_spend"] > 0

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
