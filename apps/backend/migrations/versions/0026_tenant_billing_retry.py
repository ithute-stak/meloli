"""Add tenant subscription billing records and publishing retry state.

Revision ID: 0026_tenant_billing_retry
Revises: 0025_competition_certification
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_tenant_billing_retry"
down_revision = "0025_competition_certification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_subscriptions", sa.Column("reminder_stage", sa.String(length=40), nullable=True))
    op.add_column("campaigns", sa.Column("publishing_retry_exhausted_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "tenant_subscription_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("tenant_plans.id"), nullable=False),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("billing_period", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="LSL"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="issued"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("invoice_number"),
    )
    op.create_index("ix_tenant_subscription_invoices_tenant_id", "tenant_subscription_invoices", ["tenant_id"])
    op.create_index("ix_tenant_subscription_invoices_plan_id", "tenant_subscription_invoices", ["plan_id"])
    op.create_index("ix_tenant_subscription_invoices_invoice_number", "tenant_subscription_invoices", ["invoice_number"])
    op.create_index("ix_tenant_subscription_invoices_status", "tenant_subscription_invoices", ["status"])

    op.create_table(
        "tenant_subscription_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("tenant_subscription_invoices.id"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="LSL"),
        sa.Column("method", sa.String(length=80), nullable=False, server_default="bank_transfer"),
        sa.Column("reference", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("verification_code", sa.String(length=40), nullable=True),
        sa.Column("confirmed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("verification_code"),
    )
    op.create_index("ix_tenant_subscription_payments_invoice_id", "tenant_subscription_payments", ["invoice_id"])
    op.create_index("ix_tenant_subscription_payments_tenant_id", "tenant_subscription_payments", ["tenant_id"])
    op.create_index("ix_tenant_subscription_payments_reference", "tenant_subscription_payments", ["reference"])
    op.create_index("ix_tenant_subscription_payments_status", "tenant_subscription_payments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tenant_subscription_payments_status", table_name="tenant_subscription_payments")
    op.drop_index("ix_tenant_subscription_payments_reference", table_name="tenant_subscription_payments")
    op.drop_index("ix_tenant_subscription_payments_tenant_id", table_name="tenant_subscription_payments")
    op.drop_index("ix_tenant_subscription_payments_invoice_id", table_name="tenant_subscription_payments")
    op.drop_table("tenant_subscription_payments")
    op.drop_index("ix_tenant_subscription_invoices_status", table_name="tenant_subscription_invoices")
    op.drop_index("ix_tenant_subscription_invoices_invoice_number", table_name="tenant_subscription_invoices")
    op.drop_index("ix_tenant_subscription_invoices_plan_id", table_name="tenant_subscription_invoices")
    op.drop_index("ix_tenant_subscription_invoices_tenant_id", table_name="tenant_subscription_invoices")
    op.drop_table("tenant_subscription_invoices")
    op.drop_column("campaigns", "publishing_retry_exhausted_at")
    op.drop_column("tenant_subscriptions", "reminder_stage")
