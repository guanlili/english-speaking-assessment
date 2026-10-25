"""add llm token columns to admin_metrics_daily

Revision ID: c26692710d34
Revises: 988c9d601a00
Create Date: 2026-10-25

LLM 真实 token 记账（Ark usage）：当日累计 in/out，null=未记账。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c26692710d34"
down_revision = "988c9d601a00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_metrics_daily",
        sa.Column("llm_tokens_in", sa.Integer(), nullable=True),
    )
    op.add_column(
        "admin_metrics_daily",
        sa.Column("llm_tokens_out", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admin_metrics_daily", "llm_tokens_out")
    op.drop_column("admin_metrics_daily", "llm_tokens_in")
