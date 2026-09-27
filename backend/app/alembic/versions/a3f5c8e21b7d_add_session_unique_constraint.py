"""add session unique constraint

Revision ID: a3f5c8e21b7d
Revises: 2c7f71022d00
Create Date: 2026-09-27 09:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f5c8e21b7d"
down_revision = "2c7f71022d00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_practice_session_unique",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode"],
        unique=True,
        postgresql_where=op.f("passage_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_practice_session_unique",
        table_name="practice_session",
        postgresql_where=op.f("passage_id IS NOT NULL"),
    )
