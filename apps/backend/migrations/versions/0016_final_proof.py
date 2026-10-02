"""Add advertiser final-proof approval fields.

Revision ID: 0016_final_proof
Revises: 0015_credit_notes
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_final_proof"
down_revision = "0015_credit_notes"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("campaigns")}
    additions = [
        ("proof_status", sa.Column("proof_status", sa.String(length=40), nullable=False, server_default="not_requested")),
        ("proof_requested_at", sa.Column("proof_requested_at", sa.DateTime(timezone=True), nullable=True)),
        ("proof_approved_at", sa.Column("proof_approved_at", sa.DateTime(timezone=True), nullable=True)),
        ("proof_feedback", sa.Column("proof_feedback", sa.Text(), nullable=True)),
        ("proof_requested_by_user_id", sa.Column("proof_requested_by_user_id", sa.Integer(), nullable=True)),
        ("proof_approved_by_user_id", sa.Column("proof_approved_by_user_id", sa.Integer(), nullable=True)),
    ]
    for name, column in additions:
        if name not in cols:
            op.add_column("campaigns", column)
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("campaigns")}
    if "ix_campaigns_proof_status" not in indexes:
        op.create_index("ix_campaigns_proof_status", "campaigns", ["proof_status"], unique=False)

def downgrade() -> None:
    bind = op.get_bind()
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("campaigns")}
    if "ix_campaigns_proof_status" in indexes:
        op.drop_index("ix_campaigns_proof_status", table_name="campaigns")
    cols = {c["name"] for c in sa.inspect(bind).get_columns("campaigns")}
    for name in ("proof_approved_by_user_id","proof_requested_by_user_id","proof_feedback","proof_approved_at","proof_requested_at","proof_status"):
        if name in cols:
            op.drop_column("campaigns", name)
