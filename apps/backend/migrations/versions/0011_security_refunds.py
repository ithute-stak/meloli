"""Add password reset tokens and refund requests.

Revision ID: 0011_security_refunds
Revises: 0010_corporate_invoices
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0011_security_refunds"
down_revision = "0010_corporate_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("password_reset_tokens", "refund_requests"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "refund_requests" in tables:
        op.drop_table("refund_requests")
    if "password_reset_tokens" in tables:
        op.drop_table("password_reset_tokens")
