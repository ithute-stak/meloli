"""Track campaign cancellation separately.

Revision ID: 0013_campaign_cancellation
Revises: 0012_auth_version
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_campaign_cancellation"
down_revision = "0012_auth_version"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("campaigns")}
    if "cancelled_at" not in cols:
        op.add_column("campaigns", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    if "cancellation_reason" not in cols:
        op.add_column("campaigns", sa.Column("cancellation_reason", sa.Text(), nullable=True))
    if "cancelled_by_user_id" not in cols:
        op.add_column("campaigns", sa.Column("cancelled_by_user_id", sa.Integer(), nullable=True))

def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("campaigns")}
    for name in ("cancelled_by_user_id","cancellation_reason","cancelled_at"):
        if name in cols:
            op.drop_column("campaigns", name)
