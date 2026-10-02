"""Add corporate settlement history.

Revision ID: 0008_corporate_settlements
Revises: 0007_notification_delivery
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0008_corporate_settlements"
down_revision = "0007_notification_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "corporate_settlements" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["corporate_settlements"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "corporate_settlements" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("corporate_settlements")
