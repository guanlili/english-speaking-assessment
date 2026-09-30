"""replace practice_session partial unique indexes with immutable-key design

Revision ID: b8f3e4a0c6d2
Revises: 7a1b2c3d4e5f
Create Date: 2026-09-29 12:00:00.000000

将 practice_session 的四个部分唯一索引替换为三个基于不可变锚的索引：
- 按发布 assignment_id 唯一（assignment_id 从不 SET NULL，删篇不冲突）
- 自主练习每日一条（用 COALESCE(passage_id::text, '') 容忍 passage_id 被 SET NULL）
- 主题探索按篇目唯一
"""
import sqlalchemy as sa
from alembic import op

revision = "b8f3e4a0c6d2"
down_revision = "7a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_practice_session_unique", table_name="practice_session")
    op.drop_index("ix_practice_session_unique_legacy_passage", table_name="practice_session")
    op.drop_index("ix_practice_session_unique_null_passage", table_name="practice_session")
    op.drop_index("ix_practice_session_unique_null_passage_legacy", table_name="practice_session")

    op.create_index(
        "ix_practice_session_by_assignment",
        "practice_session",
        ["student_id", "session_date", "mode", "assignment_id"],
        unique=True,
        postgresql_where=sa.text("assignment_id IS NOT NULL"),
    )
    # COALESCE 表达式索引：passage_id 被 ON DELETE SET NULL 后仍落在同一条唯一键
    op.execute(
        "CREATE UNIQUE INDEX ix_practice_session_self_practice "
        "ON practice_session (student_id, session_date, COALESCE(passage_id::text, '')) "
        "WHERE mode = 'daily' AND assignment_id IS NULL"
    )
    op.create_index(
        "ix_practice_session_explore",
        "practice_session",
        ["student_id", "session_date", "mode", "passage_id"],
        unique=True,
        postgresql_where=sa.text("mode = 'explore' AND passage_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ix_practice_session_by_assignment", table_name="practice_session")
    op.execute("DROP INDEX IF EXISTS ix_practice_session_self_practice")
    op.drop_index("ix_practice_session_explore", table_name="practice_session")

    op.create_index(
        "ix_practice_session_unique",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode", "assignment_id"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NOT NULL AND assignment_id IS NOT NULL"),
    )
    op.create_index(
        "ix_practice_session_unique_legacy_passage",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NOT NULL AND assignment_id IS NULL"),
    )
    op.create_index(
        "ix_practice_session_unique_null_passage",
        "practice_session",
        ["student_id", "session_date", "mode", "assignment_id"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NULL AND assignment_id IS NOT NULL"),
    )
    op.create_index(
        "ix_practice_session_unique_null_passage_legacy",
        "practice_session",
        ["student_id", "session_date", "mode"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NULL AND assignment_id IS NULL"),
    )
