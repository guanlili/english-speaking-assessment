"""add teacher feedback and targeted followup snapshots

Revision ID: b22ce1e19087
Revises: 08033814b327
Create Date: 2026-10-16 14:12:57.633539

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b22ce1e19087'
down_revision = '08033814b327'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attempt", sa.Column("teacher_feedback", sa.String(4000), nullable=True))
    op.add_column("attempt", sa.Column("teacher_focus", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("attempt", sa.Column("teacher_feedback_author", sa.String(255), nullable=True))
    op.add_column("attempt", sa.Column("teacher_feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attempt", sa.Column("teacher_feedback_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("classroom_exercise", sa.Column("target_students", sa.JSON(), nullable=True))
    op.add_column("classroom_exercise", sa.Column("source_exercise_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_exercise_followup_source", "classroom_exercise", "classroom_exercise", ["source_exercise_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_practice_session_followup", "practice_session", ["student_id", "assignment_id"], unique=True, postgresql_where=sa.text("mode = 'followup' AND assignment_id IS NOT NULL"))


def downgrade():
    op.drop_index("ix_practice_session_followup", table_name="practice_session")
    op.drop_constraint("fk_exercise_followup_source", "classroom_exercise", type_="foreignkey")
    op.drop_column("classroom_exercise", "source_exercise_id")
    op.drop_column("classroom_exercise", "target_students")
    for column in ("teacher_feedback_revision", "teacher_feedback_at", "teacher_feedback_author", "teacher_focus", "teacher_feedback"):
        op.drop_column("attempt", column)
