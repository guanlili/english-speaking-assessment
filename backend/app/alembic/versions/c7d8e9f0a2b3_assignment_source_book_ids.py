"""assignment source book ids for trend filtering (#517)

Revision ID: c7d8e9f0a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-11-25 16:00:00.000000

- ``vocabulary_assignment`` 新增 ``source_book_ids`` JSON 列表：发布词单归属的
  词库 id 集合（按请求 book_id 或显式 word_ids 的归属词库推导），供教师趋势
  按词库筛选；存量行为空列表。
- 不改写既有 ``snapshot_items``；本列仅作筛选索引用途。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7d8e9f0a2b3"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vocabulary_assignment",
        sa.Column(
            "source_book_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    # 存量行兜底：server_default 已在 ADD COLUMN 时回填，这里再显式归一一次。
    op.execute(
        sa.text(
            "UPDATE vocabulary_assignment SET source_book_ids = '[]'::json "
            "WHERE source_book_ids IS NULL"
        )
    )


def downgrade():
    op.drop_column("vocabulary_assignment", "source_book_ids")
