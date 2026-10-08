"""vocab_book_item position 平局回填

Revision ID: c4e8f9a21b76
Revises: b7e2d4c9a1f3
Create Date: 2026-10-08

历史 bug：create_book 建库带词时 VocabularyBookItem 漏传 position，
全部默认 0 → ORDER BY position 全平局 → Postgres 平局返回顺序不稳定
（教师预览词序与学生测验词序可能不一致；CI 与本地实测返回不同顺序）。

回填：整本书按 (position, ctid) 重排为连续 1..n——已有真实顺序的库保持
原相对顺序（ctid 物理序近似插入序，仅用于打破平局）。downgrade 无法
还原平局原值（本就是病态数据），空操作即可。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4e8f9a21b76"
down_revision = "b7e2d4c9a1f3"
branch_labels = None
depends_on = None

_RENUMBER_SQL = """
WITH ordered AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY book_id ORDER BY position, ctid) AS rn
    FROM vocabulary_book_item
)
UPDATE vocabulary_book_item AS item
SET position = ordered.rn
FROM ordered
WHERE item.id = ordered.id
  AND item.position <> ordered.rn
"""


def upgrade() -> None:
    op.execute(_RENUMBER_SQL)


def downgrade() -> None:
    # 平局的原始 position 无业务含义且不可恢复，降级不还原
    pass
