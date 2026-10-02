"""Add durable realtime event stream.

Revision ID: 0027_realtime_events
Revises: 0026_tenant_billing_retry
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_realtime_events"
down_revision = "0026_tenant_billing_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "realtime_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_realtime_events_tenant_id", "realtime_events", ["tenant_id"])
    op.create_index("ix_realtime_events_user_id", "realtime_events", ["user_id"])
    op.create_index("ix_realtime_events_topic", "realtime_events", ["topic"])
    op.create_index("ix_realtime_events_created_at", "realtime_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_realtime_events_created_at", table_name="realtime_events")
    op.drop_index("ix_realtime_events_topic", table_name="realtime_events")
    op.drop_index("ix_realtime_events_user_id", table_name="realtime_events")
    op.drop_index("ix_realtime_events_tenant_id", table_name="realtime_events")
    op.drop_table("realtime_events")
