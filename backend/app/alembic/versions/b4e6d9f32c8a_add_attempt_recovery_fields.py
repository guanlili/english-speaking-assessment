"""add attempt idempotency and recovery fields

Revision ID: b4e6d9f32c8a
Revises: a3f5c8e21b7d
Create Date: 2026-09-27 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b4e6d9f32c8a"
down_revision = "a3f5c8e21b7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attempt",
        sa.Column("idempotency_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "attempt",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "attempt",
        sa.Column("claimed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_attempt_idempotency_key", "attempt", ["idempotency_key"])


def downgrade() -> None:
    op.drop_index("ix_attempt_idempotency_key", table_name="attempt")
    op.drop_column("attempt", "claimed_at")
    op.drop_column("attempt", "retry_count")
    op.drop_column("attempt", "idempotency_key")
