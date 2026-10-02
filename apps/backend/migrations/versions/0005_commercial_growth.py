"""Add commercial growth models.

Revision ID: 0005_commercial_growth
Revises: 0004_retention_support
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0005_commercial_growth"
down_revision = "0004_retention_support"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("promo_codes", "corporate_accounts", "subscription_plans", "advertiser_subscriptions"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("advertiser_subscriptions", "subscription_plans", "corporate_accounts", "promo_codes"):
        if name in tables:
            op.drop_table(name)
