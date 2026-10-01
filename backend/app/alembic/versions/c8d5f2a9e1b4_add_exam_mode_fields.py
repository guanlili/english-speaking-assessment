"""add exam mode fields (mock exam: time limit + anti-cheat)

Revision ID: c8d5f2a9e1b4
Revises: a9c4e7f1b3d6
Create Date: 2026-10-01 10:00:00.000000

模考模式（2026-10-01）：
- classroom_exercise.is_exam / time_limit_minutes：发布为模考 + 整场限时
- practice_session.exam_started_at / exam_ended_at：学生首次打开开考、
  到时/交卷惰性终结；tab_switch_count：前端切屏上报计数（教师可见）
"""
import sqlalchemy as sa
from alembic import op

revision = "c8d5f2a9e1b4"
down_revision = "a9c4e7f1b3d6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "classroom_exercise",
        sa.Column(
            "is_exam",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "classroom_exercise",
        sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "practice_session",
        sa.Column("exam_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "practice_session",
        sa.Column("exam_ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "practice_session",
        sa.Column(
            "tab_switch_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade():
    op.drop_column("practice_session", "tab_switch_count")
    op.drop_column("practice_session", "exam_ended_at")
    op.drop_column("practice_session", "exam_started_at")
    op.drop_column("classroom_exercise", "time_limit_minutes")
    op.drop_column("classroom_exercise", "is_exam")
