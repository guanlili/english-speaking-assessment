"""vocab quiz mode assignment and session fields

Revision ID: d7b3e9c4a1f2
Revises: c9a4f1d2e8b3
Create Date: 2026-10-06 15:30:00.000000

词汇限时测验：
- vocabulary_assignment：duration_minutes / pass_line / 成绩与答案公布时间
- vocabulary_assignment_target：retake_granted_at（教师单独授权一次补考）
- vocabulary_session：quiz_started_at（学生明确开始才计时）/ end_reason
  （manual=已交卷、timeout=超时服务端结算；status 仍用 submitted）

全部为可空或带默认的新增列，存量行含义不变；downgrade 无损（只删列）。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "d7b3e9c4a1f2"
down_revision = "c9a4f1d2e8b3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vocabulary_assignment",
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "vocabulary_assignment",
        sa.Column(
            "pass_line", sa.Integer(), server_default="60", nullable=False
        ),
    )
    op.add_column(
        "vocabulary_assignment",
        sa.Column("grades_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vocabulary_assignment",
        sa.Column("answers_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vocabulary_assignment_target",
        sa.Column("retake_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vocabulary_session",
        sa.Column("quiz_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vocabulary_session",
        sa.Column(
            "end_reason", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True
        ),
    )


def downgrade():
    op.drop_column("vocabulary_session", "end_reason")
    op.drop_column("vocabulary_session", "quiz_started_at")
    op.drop_column("vocabulary_assignment_target", "retake_granted_at")
    op.drop_column("vocabulary_assignment", "answers_published_at")
    op.drop_column("vocabulary_assignment", "grades_published_at")
    op.drop_column("vocabulary_assignment", "pass_line")
    op.drop_column("vocabulary_assignment", "duration_minutes")
