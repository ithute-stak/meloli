# Meloli Airwaves Advertising Portal

A responsive client-to-publisher advertising platform for Meloli Airwaves Media. Advertisers register, create campaigns, upload a single video or up to 10 carousel images, submit payment details and track editorial decisions. Meloli staff verify payments, review content, request changes, approve and schedule campaigns, then publish approved adverts to the configured Meloli Facebook Page.

## Stack

- Next.js 16 + React 19 + TypeScript + Tailwind CSS 4
- FastAPI + SQLAlchemy + PostgreSQL
- Alembic database migrations
- Docker / Docker Compose
- Meta Graph API integration configured from the dashboard

The architecture follows the modern patterns used across Ithute and LoanHub.

## Roles

- `advertiser` — owns campaigns and payment records
- `reviewer` — reviews paid campaigns and requests changes/approves
- `publisher` — can publish approved campaigns to Facebook
- `super_admin` — full operational access plus packages and system configuration

## Core workflow

`Payment pending → Submitted → In review → Changes requested / Approved → Advertiser final proof → Scheduled → Published`

Nothing is sent to Facebook before Meloli staff approval **and advertiser final-proof approval**.

## Local development

1. Copy `.env.example` to `.env` and replace all example secrets.
2. Start the stack:

```bash
docker compose up --build
```

3. Frontend: `http://localhost:3000`
4. Backend API: `http://localhost:8000`
5. API health: `http://localhost:8000/health`

The backend runs `alembic upgrade head` before starting Uvicorn. Uploaded campaign media is stored in the `meloli_media` Docker volume and PostgreSQL data in `meloli_db`.

## Facebook / Meta configuration

Meta credentials are not hard-coded. Sign in as Super Admin and open **Settings → Facebook / Meta**. Configure:

- Meta App ID
- Meta App Secret
- Facebook Page ID
- Page access token
- Graph API version
- webhook verify token and callback URL when webhooks are needed

Secrets are encrypted before database storage and are never returned to the browser after saving. Use **Test connection** to verify Page access. `PUBLIC_BACKEND_URL` must be a publicly reachable HTTPS backend URL before Meta can fetch media uploaded to the Meloli server.

The Meta app and Page must have whatever permissions and review status Meta currently requires for Page publishing. These requirements are controlled by Meta and should be confirmed when the production app is created.

## Payments

V1 supports traceable manual/offline payment submissions and Meloli verification. Payment confirmation automatically moves a campaign into the editorial queue. The payment model is designed so an external payment gateway can be added without changing the campaign workflow.

Confirmed payments expose a PDF receipt endpoint. Advertisers can only access receipts and payment records for their own campaigns.

## Backups and recovery

The Compose stack includes a dedicated `backup` service. It creates:

- PostgreSQL custom-format dumps in the `meloli_backups` volume
- compressed archives of the `meloli_media` volume
- a `last-success` marker only after both artifacts pass readability checks (`pg_restore --list` and `tar -tzf`)

Key settings:

- `BACKUP_INTERVAL_SECONDS` — default `86400` (daily)
- `BACKUP_RETENTION_DAYS` — default `14`
- `BACKUP_MAX_AGE_HOURS` — default `30`; older backups are flagged as stale in Operations Control Centre

A restore should be performed as an operator maintenance task, not from the web UI. Use a separate test database/volume first, restore the selected PostgreSQL dump with `pg_restore`, extract the matching media archive, run `alembic upgrade head`, and verify `/health`, campaign documents, media access and login before restoring production. Keep the original production volumes untouched until the drill has been validated.
## Growth, referrals and corporate API

Super Admin can create referral partners in **Growth & Referrals**. Each partner receives a code and can share a registration link such as `/register?ref=AGENCY10`. Referred advertisers are permanently attributed to that partner, and commission reporting uses only currently confirmed paid transactions.

Approved corporate-credit advertisers can also receive scoped machine credentials from **Corporate API**. The API key is shown once, stored only as a SHA-256 hash, and can be disabled from the dashboard.

Corporate clients can:

- submit campaigns using `POST /api/v1/corporate-api/campaigns` with the `X-API-Key` header
- read their own campaign statuses from `GET /api/v1/corporate-api/campaigns`
- receive HMAC-SHA256 signed campaign lifecycle webhooks when a webhook URL is configured

Webhook requests include the `X-Meloli-Signature: sha256=...` header. Corporate API campaign submission charges the advertiser’s approved corporate credit account immediately and will fail when available credit is insufficient.

## Progressive Web App

The frontend includes a web-app manifest, Meloli PWA icons and a service worker. Eligible browsers can install the portal as a standalone app. The service worker keeps a lightweight navigation shell available when the network is temporarily unavailable; transactional/API operations still require connectivity.
## Testing and CI

GitHub Actions runs:

- backend smoke tests using an isolated SQLite test database
- frontend TypeScript checks
- production frontend build

Run backend tests locally:

```bash
cd apps/backend
PYTHONPATH=. pytest -q
```

Run frontend validation:

```bash
cd apps/frontend
corepack enable
pnpm install
pnpm typecheck
pnpm build
```

## Production checklist

- Use strong independent `JWT_SECRET` and `SETTINGS_ENCRYPTION_KEY` values.
- Set `SUPER_ADMIN_EMAIL` and `SUPER_ADMIN_PASSWORD` only through deployment secrets.
- Set production `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL` and `PUBLIC_BACKEND_URL`.
- Put the frontend and backend behind HTTPS.
- Configure backups for PostgreSQL and the media volume.
- Configure and verify the production Meta app/Page integration from the dashboard.
- Run CI and device QA before merging/deploying a release.
