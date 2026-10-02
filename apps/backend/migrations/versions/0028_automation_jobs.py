"""Add automation job state tracking.

Revision ID: 0028_automation_jobs
Revises: 0027_realtime_events
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_automation_jobs"
down_revision = "0027_realtime_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_job_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_key", sa.String(length=100), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=30), nullable=False, server_default="never"),
        sa.Column("last_result", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_key"),
    )
    op.create_index("ix_automation_job_states_job_key", "automation_job_states", ["job_key"])
    op.create_index("ix_automation_job_states_last_status", "automation_job_states", ["last_status"])


def downgrade() -> None:
    op.drop_index("ix_automation_job_states_last_status", table_name="automation_job_states")
    op.drop_index("ix_automation_job_states_job_key", table_name="automation_job_states")
    op.drop_table("automation_job_states")
