"""add classroom activity review tags and copy provenance

Revision ID: b3d01b77c78a
Revises: c4b8e2d6f913
Create Date: 2026-10-17 14:32:57.085961

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3d01b77c78a'
down_revision = 'c4b8e2d6f913'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("student", sa.Column("classroom_activity", sa.JSON(), nullable=True))
    op.add_column("attempt", sa.Column("teacher_review_tags", sa.JSON(), nullable=True))
    for table in ("passage", "repeat_sentence", "scenario_question", "instruction"):
        op.add_column(table, sa.Column("copied_from_id", sa.Uuid(), nullable=True))


def downgrade():
    for table in ("instruction", "scenario_question", "repeat_sentence", "passage"):
        op.drop_column(table, "copied_from_id")
    op.drop_column("attempt", "teacher_review_tags")
    op.drop_column("student", "classroom_activity")
