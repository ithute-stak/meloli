"""Add corporate invoice lines and credit notes.

Revision ID: 0015_credit_notes
Revises: 0014_auth_sessions
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0015_credit_notes"
down_revision = "0014_auth_sessions"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("corporate_invoice_lines", "corporate_credit_notes"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "corporate_credit_notes" in tables:
        op.drop_table("corporate_credit_notes")
    if "corporate_invoice_lines" in tables:
        op.drop_table("corporate_invoice_lines")
