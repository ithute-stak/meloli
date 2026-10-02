"""Link payments to promotion codes.

Revision ID: 0009_payment_promos
Revises: 0008_corporate_settlements
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_payment_promos"
down_revision = "0008_corporate_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("payments")}
    if "promo_code_id" not in cols:
        op.add_column("payments", sa.Column("promo_code_id", sa.Integer(), nullable=True))
        try:
            op.create_index("ix_payments_promo_code_id", "payments", ["promo_code_id"])
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("payments")}
    if "promo_code_id" in cols:
        try:
            op.drop_index("ix_payments_promo_code_id", table_name="payments")
        except Exception:
            pass
        op.drop_column("payments", "promo_code_id")
