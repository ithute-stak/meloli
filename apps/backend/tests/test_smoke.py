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
from app.main import app  # noqa: E402


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

        notifications = client.get("/api/v1/notifications", headers=auth(advertiser_token))
        assert notifications.status_code == 200
        assert len(notifications.json()) >= 2

        summary = client.get("/api/v1/admin/reports/summary", headers=auth(admin_token))
        assert summary.status_code == 200
        assert summary.json()["campaigns"] >= 1
        assert summary.json()["paid_payments"] >= 1
