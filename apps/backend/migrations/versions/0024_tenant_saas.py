"""Add SaaS plans and subscriptions for Page tenants.

Revision ID: 0024_tenant_saas
Revises: 0023_tenant_packages
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_tenant_saas"
down_revision = "0023_tenant_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("monthly_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("annual_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="LSL"),
        sa.Column("max_staff", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_campaigns_monthly", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("custom_domains", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("competition_certification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_tenant_plans_code", "tenant_plans", ["code"])
    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("tenant_plans.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="trialing"),
        sa.Column("billing_period", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="LSL"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_index("ix_tenant_subscriptions_tenant_id", "tenant_subscriptions", ["tenant_id"])
    op.create_index("ix_tenant_subscriptions_plan_id", "tenant_subscriptions", ["plan_id"])
    op.create_index("ix_tenant_subscriptions_status", "tenant_subscriptions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tenant_subscriptions_status", table_name="tenant_subscriptions")
    op.drop_index("ix_tenant_subscriptions_plan_id", table_name="tenant_subscriptions")
    op.drop_index("ix_tenant_subscriptions_tenant_id", table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")
    op.drop_index("ix_tenant_plans_code", table_name="tenant_plans")
    op.drop_table("tenant_plans")
