"""Add persistent corporate invoices.

Revision ID: 0010_corporate_invoices
Revises: 0009_payment_promos
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0010_corporate_invoices"
down_revision = "0009_payment_promos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "corporate_invoices" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["corporate_invoices"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "corporate_invoices" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("corporate_invoices")
