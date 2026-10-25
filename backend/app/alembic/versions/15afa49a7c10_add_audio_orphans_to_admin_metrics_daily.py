"""add audio orphans to admin_metrics_daily

Revision ID: 15afa49a7c10
Revises: c26692710d34
Create Date: 2026-10-25

性能区孤儿音频数日快照（null=当日无采样）。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "15afa49a7c10"
down_revision = "c26692710d34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_metrics_daily",
        sa.Column("audio_orphans", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_metrics_daily", "audio_orphans")
