"""Add campaign performance metrics.

Revision ID: 0003_campaign_performance
Revises: 0002_publication_hardening
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa

from app.db import Base
from app import models  # noqa: F401

revision = "0003_campaign_performance"
down_revision = "0002_publication_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "campaign_performance" not in set(inspector.get_table_names()):
        Base.metadata.tables["campaign_performance"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "campaign_performance" in set(inspector.get_table_names()):
        op.drop_table("campaign_performance")
