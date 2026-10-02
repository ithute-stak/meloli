"""Add referral partners and payouts.

Revision ID: 0020_referrals
Revises: 0019_review_checklist
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0020_referrals"
down_revision = "0019_review_checklist"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("referral_partners","referral_attributions","referral_payouts"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("referral_payouts","referral_attributions","referral_partners"):
        if name in tables:
            op.drop_table(name)
