"""Add revocable auth version.

Revision ID: 0012_auth_version
Revises: 0011_security_refunds
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_auth_version"
down_revision = "0011_security_refunds"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "auth_version" not in cols:
        op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))

def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "auth_version" in cols:
        op.drop_column("users", "auth_version")
