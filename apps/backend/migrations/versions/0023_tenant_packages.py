"""Make advertising packages tenant-scoped.

Revision ID: 0023_tenant_packages
Revises: 0022_multitenancy_competition
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_tenant_packages"
down_revision = "0022_multitenancy_competition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if dialect != "sqlite":
        for constraint in inspector.get_unique_constraints("advertising_packages"):
            cols = constraint.get("column_names") or []
            if cols == ["code"] and constraint.get("name"):
                op.drop_constraint(constraint["name"], "advertising_packages", type_="unique")
        existing = {c.get("name") for c in sa.inspect(bind).get_unique_constraints("advertising_packages")}
        if "uq_advertising_packages_tenant_code" not in existing:
            op.create_unique_constraint(
                "uq_advertising_packages_tenant_code",
                "advertising_packages",
                ["tenant_id", "code"],
            )

    default_row = bind.execute(sa.text("select id from tenants where slug = :slug"), {"slug": "meloli-airwaves"}).fetchone()
    if not default_row:
        return
    default_tenant_id = default_row[0]
    tenant_ids = [row[0] for row in bind.execute(sa.text("select id from tenants where id <> :id"), {"id": default_tenant_id})]
    templates = list(bind.execute(sa.text(
        "select code,name,description,price,currency,posts_included,max_media_items,allow_video,allow_carousel,active "
        "from advertising_packages where tenant_id = :tenant order by id"
    ), {"tenant": default_tenant_id}))
    for tenant_id in tenant_ids:
        for package in templates:
            exists = bind.execute(
                sa.text("select 1 from advertising_packages where tenant_id = :tenant and code = :code"),
                {"tenant": tenant_id, "code": package.code},
            ).fetchone()
            if exists:
                continue
            bind.execute(
                sa.text(
                    "insert into advertising_packages "
                    "(tenant_id,code,name,description,price,currency,posts_included,max_media_items,allow_video,allow_carousel,active) "
                    "values (:tenant,:code,:name,:description,:price,:currency,:posts,:max_media,:video,:carousel,:active)"
                ),
                {
                    "tenant": tenant_id,
                    "code": package.code,
                    "name": package.name,
                    "description": package.description,
                    "price": package.price,
                    "currency": package.currency,
                    "posts": package.posts_included,
                    "max_media": package.max_media_items,
                    "video": package.allow_video,
                    "carousel": package.allow_carousel,
                    "active": package.active,
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        constraints = {c.get("name") for c in sa.inspect(bind).get_unique_constraints("advertising_packages")}
        if "uq_advertising_packages_tenant_code" in constraints:
            op.drop_constraint("uq_advertising_packages_tenant_code", "advertising_packages", type_="unique")
        op.create_unique_constraint("advertising_packages_code_key", "advertising_packages", ["code"])
