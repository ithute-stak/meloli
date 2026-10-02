"""Add immutable competition result certifications.

Revision ID: 0025_competition_certification
Revises: 0024_tenant_saas
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_competition_certification"
down_revision = "0024_tenant_saas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competition_certifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("certified_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("certified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("campaign_id"),
        sa.UniqueConstraint("snapshot_sha256"),
    )
    op.create_index("ix_competition_certifications_campaign_id", "competition_certifications", ["campaign_id"])
    op.create_index("ix_competition_certifications_snapshot_sha256", "competition_certifications", ["snapshot_sha256"])
    op.create_index("ix_competition_certifications_certified_by_user_id", "competition_certifications", ["certified_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_competition_certifications_certified_by_user_id", table_name="competition_certifications")
    op.drop_index("ix_competition_certifications_snapshot_sha256", table_name="competition_certifications")
    op.drop_index("ix_competition_certifications_campaign_id", table_name="competition_certifications")
    op.drop_table("competition_certifications")
