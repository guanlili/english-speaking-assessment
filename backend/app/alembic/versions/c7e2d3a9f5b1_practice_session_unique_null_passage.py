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
