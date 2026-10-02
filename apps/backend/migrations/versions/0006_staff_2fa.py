"""Add staff two-factor authentication fields.

Revision ID: 0006_staff_2fa
Revises: 0005_commercial_growth
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision="0006_staff_2fa"
down_revision="0005_commercial_growth"
branch_labels=None
depends_on=None

def upgrade() -> None:
    bind=op.get_bind()
    cols={c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "two_factor_enabled" not in cols:
        op.add_column("users",sa.Column("two_factor_enabled",sa.Boolean(),nullable=False,server_default=sa.false()))
    if "totp_secret" not in cols:
        op.add_column("users",sa.Column("totp_secret",sa.Text(),nullable=True))

def downgrade() -> None:
    bind=op.get_bind()
    cols={c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "totp_secret" in cols: op.drop_column("users","totp_secret")
    if "two_factor_enabled" in cols: op.drop_column("users","two_factor_enabled")
