"""add unique index for practice_session when passage_id IS NULL

Revision ID: c7e2d3a9f5b1
Revises: a8e41d2c7f10
Create Date: 2026-09-29 10:00:00.000000

修复按题指派且无篇目时，daily 会话可能并发创建重复的问题：
新增部分唯一索引覆盖 passage_id IS NULL 的场景。
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c7e2d3a9f5b1'
down_revision = 'a8e41d2c7f10'
branch_labels = None
depends_on = None


def upgrade():
    # 先清理竞态期间已产生的重复 NULL-passage 会话（同学生同日同模式保留最新一条）。
    # 被删的是 bug 期脏会话；其上若有作答随外键级联删除（生产当前为测试数据）。
    op.execute(
        """
        DELETE FROM practice_session ps
        USING practice_session keep
        WHERE ps.passage_id IS NULL
          AND keep.passage_id IS NULL
          AND ps.student_id = keep.student_id
          AND ps.session_date = keep.session_date
          AND ps.mode = keep.mode
          AND (ps.created_at, ps.id) < (keep.created_at, keep.id)
        """
    )
    op.create_index(
        "ix_practice_session_unique_null_passage",
        "practice_session",
        ["student_id", "session_date", "mode"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NULL"),
    )


def downgrade():
    op.drop_index(
        "ix_practice_session_unique_null_passage",
        table_name="practice_session",
        postgresql_where=sa.text("passage_id IS NULL"),
    )
