"""Add campaign moderation checklist.

Revision ID: 0019_review_checklist
Revises: 0018_package_media_rules
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0019_review_checklist"
down_revision = "0018_package_media_rules"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    if "campaign_review_checklists" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["campaign_review_checklists"].create(bind=bind, checkfirst=True)

def downgrade() -> None:
    bind = op.get_bind()
    if "campaign_review_checklists" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("campaign_review_checklists")
