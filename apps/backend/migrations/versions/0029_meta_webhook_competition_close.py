"""Add competition closing and Meta webhook inbox.

Revision ID: 0029_meta_webhook_competition_close
Revises: 0028_automation_jobs
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_meta_webhook_competition_close"
down_revision = "0028_automation_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("competition_closes_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("competition_closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("competition_auto_certify", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_campaigns_competition_closes_at", "campaigns", ["competition_closes_at"])

    op.create_table(
        "meta_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("page_id", sa.String(length=120), nullable=True),
        sa.Column("object_type", sa.String(length=80), nullable=False, server_default="page"),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("payload_sha256"),
    )
    op.create_index("ix_meta_webhook_events_tenant_id", "meta_webhook_events", ["tenant_id"])
    op.create_index("ix_meta_webhook_events_page_id", "meta_webhook_events", ["page_id"])
    op.create_index("ix_meta_webhook_events_payload_sha256", "meta_webhook_events", ["payload_sha256"])
    op.create_index("ix_meta_webhook_events_status", "meta_webhook_events", ["status"])
    op.create_index("ix_meta_webhook_events_received_at", "meta_webhook_events", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_meta_webhook_events_received_at", table_name="meta_webhook_events")
    op.drop_index("ix_meta_webhook_events_status", table_name="meta_webhook_events")
    op.drop_index("ix_meta_webhook_events_payload_sha256", table_name="meta_webhook_events")
    op.drop_index("ix_meta_webhook_events_page_id", table_name="meta_webhook_events")
    op.drop_index("ix_meta_webhook_events_tenant_id", table_name="meta_webhook_events")
    op.drop_table("meta_webhook_events")
    op.drop_index("ix_campaigns_competition_closes_at", table_name="campaigns")
    op.drop_column("campaigns", "competition_auto_certify")
    op.drop_column("campaigns", "competition_closed_at")
    op.drop_column("campaigns", "competition_closes_at")
