"""Add outbound notification delivery queue.

Revision ID: 0007_notification_delivery
Revises: 0006_staff_2fa
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision="0007_notification_delivery"
down_revision="0006_staff_2fa"
branch_labels=None
depends_on=None

def upgrade() -> None:
    bind=op.get_bind()
    if "notification_deliveries" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["notification_deliveries"].create(bind=bind,checkfirst=True)

def downgrade() -> None:
    bind=op.get_bind()
    if "notification_deliveries" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("notification_deliveries")
