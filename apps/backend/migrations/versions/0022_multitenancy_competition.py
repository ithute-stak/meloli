"""Add multi-tenancy and competition voting.

Revision ID: 0022_multitenancy_competition
Revises: 0021_corporate_api
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa
from app.db import Base
from app import models  # noqa: F401

revision = "0022_multitenancy_competition"
down_revision = "0021_corporate_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for name in ("tenants", "tenant_domains", "tenant_settings"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)

    users_cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "tenant_id" not in users_cols:
        op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
    if "is_tenant_admin" not in users_cols:
        op.add_column("users", sa.Column("is_tenant_admin", sa.Boolean(), nullable=False, server_default=sa.false()))

    package_cols = {c["name"] for c in sa.inspect(bind).get_columns("advertising_packages")}
    if "tenant_id" not in package_cols:
        op.add_column("advertising_packages", sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_index("ix_advertising_packages_tenant_id", "advertising_packages", ["tenant_id"], unique=False)

    campaign_cols = {c["name"] for c in sa.inspect(bind).get_columns("campaigns")}
    if "tenant_id" not in campaign_cols:
        op.add_column("campaigns", sa.Column("tenant_id", sa.Integer(), nullable=True))
        op.create_index("ix_campaigns_tenant_id", "campaigns", ["tenant_id"], unique=False)
    if "engagement_mode" not in campaign_cols:
        op.add_column("campaigns", sa.Column("engagement_mode", sa.String(length=50), nullable=False, server_default="normal"))
        op.create_index("ix_campaigns_engagement_mode", "campaigns", ["engagement_mode"], unique=False)

    tables = set(sa.inspect(bind).get_table_names())
    for name in ("competition_comments", "competition_reactions"):
        if name not in tables:
            Base.metadata.tables[name].create(bind=bind, checkfirst=True)

    existing = bind.execute(sa.text("select id from tenants where slug = :slug"), {"slug": "meloli-airwaves"}).fetchone()
    if existing:
        tenant_id = existing[0]
    else:
        tenant_id = bind.execute(
            sa.text(
                "insert into tenants (name, slug, facebook_page_name, accent_color, active) "
                "values (:name, :slug, :page, :accent, :active) returning id"
            ),
            {"name": "Meloli Airwaves", "slug": "meloli-airwaves", "page": "Meloli Airwaves", "accent": "#e31545", "active": True},
        ).scalar_one()

    bind.execute(sa.text("update users set tenant_id = :tenant where tenant_id is null"), {"tenant": tenant_id})
    bind.execute(sa.text("update advertising_packages set tenant_id = :tenant where tenant_id is null"), {"tenant": tenant_id})
    bind.execute(sa.text("update campaigns set tenant_id = :tenant where tenant_id is null"), {"tenant": tenant_id})


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for name in ("competition_reactions", "competition_comments", "tenant_settings", "tenant_domains", "tenants"):
        if name in tables:
            op.drop_table(name)
    campaign_cols = {c["name"] for c in sa.inspect(bind).get_columns("campaigns")}
    if "engagement_mode" in campaign_cols:
        op.drop_index("ix_campaigns_engagement_mode", table_name="campaigns")
        op.drop_column("campaigns", "engagement_mode")
    if "tenant_id" in campaign_cols:
        op.drop_index("ix_campaigns_tenant_id", table_name="campaigns")
        op.drop_column("campaigns", "tenant_id")
    package_cols = {c["name"] for c in sa.inspect(bind).get_columns("advertising_packages")}
    if "tenant_id" in package_cols:
        op.drop_index("ix_advertising_packages_tenant_id", table_name="advertising_packages")
        op.drop_column("advertising_packages", "tenant_id")
    users_cols = {c["name"] for c in sa.inspect(bind).get_columns("users")}
    if "is_tenant_admin" in users_cols:
        op.drop_column("users", "is_tenant_admin")
    if "tenant_id" in users_cols:
        op.drop_index("ix_users_tenant_id", table_name="users")
        op.drop_column("users", "tenant_id")
