"""Add publication tracking and notifications to pre-migration foundation databases.

Revision ID: 0002_publication_hardening
Revises: 0001_initial
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa

from app.db import Base
from app import models  # noqa: F401

revision = "0002_publication_hardening"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "campaigns" in tables:
        columns = {column["name"] for column in inspector.get_columns("campaigns")}
        if "published_at" not in columns:
            op.add_column("campaigns", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    # create_all/checkfirst safely creates only the new tables/enums on an older
    # foundation database while remaining a no-op on fresh installations.
    for table_name in ("publication_attempts", "notifications"):
        if table_name not in tables:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "notifications" in tables:
        op.drop_table("notifications")
    if "publication_attempts" in tables:
        op.drop_table("publication_attempts")
    if "campaigns" in tables:
        columns = {column["name"] for column in inspector.get_columns("campaigns")}
        if "published_at" in columns:
            op.drop_column("campaigns", "published_at")
