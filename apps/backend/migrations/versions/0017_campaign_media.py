"""Add ordered campaign media.

Revision ID: 0017_campaign_media
Revises: 0016_final_proof
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0017_campaign_media"
down_revision = "0016_final_proof"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    if "campaign_media" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["campaign_media"].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    if "campaign_media" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("campaign_media")
