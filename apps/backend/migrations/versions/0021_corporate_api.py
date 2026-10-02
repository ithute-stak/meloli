"""Add corporate API clients.

Revision ID: 0021_corporate_api
Revises: 0020_referrals
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0021_corporate_api"
down_revision = "0020_referrals"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    if "corporate_api_clients" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["corporate_api_clients"].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    if "corporate_api_clients" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("corporate_api_clients")
