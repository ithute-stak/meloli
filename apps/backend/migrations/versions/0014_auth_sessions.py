"""Add persistent login sessions.

Revision ID: 0014_auth_sessions
Revises: 0013_campaign_cancellation
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0014_auth_sessions"
down_revision = "0013_campaign_cancellation"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    if "auth_sessions" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["auth_sessions"].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    if "auth_sessions" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("auth_sessions")
