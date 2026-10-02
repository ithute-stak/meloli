"""Add package media rules.

Revision ID: 0018_package_media_rules
Revises: 0017_campaign_media
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_package_media_rules"
down_revision = "0017_campaign_media"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("advertising_packages")}
    if "max_media_items" not in cols:
        op.add_column("advertising_packages", sa.Column("max_media_items", sa.Integer(), nullable=False, server_default="10"))
    if "allow_video" not in cols:
        op.add_column("advertising_packages", sa.Column("allow_video", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "allow_carousel" not in cols:
        op.add_column("advertising_packages", sa.Column("allow_carousel", sa.Boolean(), nullable=False, server_default=sa.true()))

def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("advertising_packages")}
    for name in ("allow_carousel","allow_video","max_media_items"):
        if name in cols:
            op.drop_column("advertising_packages", name)
