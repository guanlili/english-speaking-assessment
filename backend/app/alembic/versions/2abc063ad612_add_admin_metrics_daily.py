"""add admin_metrics_daily

Revision ID: 2abc063ad612
Revises: a3f8c1d90e42
Create Date: 2026-10-25

大盘日快照表：业务量回算 + 运行时峰值（P1 性能区历史）。
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes as sqlt
from alembic import op

# revision identifiers, used by Alembic.
revision = "2abc063ad612"
down_revision = "a3f8c1d90e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_metrics_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "attempts_done", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "attempts_failed", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "active_students", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("sessions", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "asr_seconds", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column("llm_calls_by_kind", sa.JSON(), nullable=True),
        sa.Column("provider_failures", sa.JSON(), nullable=True),
        sa.Column("queue_max_age_s", sa.Float(), nullable=True),
        sa.Column("pool_max_checked_out", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("admin_metrics_daily")
