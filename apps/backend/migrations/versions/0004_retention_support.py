"""Add support tickets and performance history.

Revision ID: 0004_retention_support
Revises: 0003_campaign_performance
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa

from app.db import Base
from app import models  # noqa: F401

revision = "0004_retention_support"
down_revision = "0003_campaign_performance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name in ("campaign_performance_snapshots", "support_tickets"):
        if table_name not in tables:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "support_tickets" in tables:
        op.drop_table("support_tickets")
    if "campaign_performance_snapshots" in tables:
        op.drop_table("campaign_performance_snapshots")
