"""Add campaign review presence.

Revision ID: 0030_campaign_review_presence
Revises: 0029_meta_webhook_competition_close
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_campaign_review_presence"
down_revision = "0029_meta_webhook_competition_close"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_review_presence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_campaign_review_presence_campaign_user"),
    )
    op.create_index("ix_campaign_review_presence_campaign_id", "campaign_review_presence", ["campaign_id"])
    op.create_index("ix_campaign_review_presence_user_id", "campaign_review_presence", ["user_id"])
    op.create_index("ix_campaign_review_presence_tenant_id", "campaign_review_presence", ["tenant_id"])
    op.create_index("ix_campaign_review_presence_last_seen_at", "campaign_review_presence", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_campaign_review_presence_last_seen_at", table_name="campaign_review_presence")
    op.drop_index("ix_campaign_review_presence_tenant_id", table_name="campaign_review_presence")
    op.drop_index("ix_campaign_review_presence_user_id", table_name="campaign_review_presence")
    op.drop_index("ix_campaign_review_presence_campaign_id", table_name="campaign_review_presence")
    op.drop_table("campaign_review_presence")
