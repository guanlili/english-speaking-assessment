"""backfill passage.topic from unit.topic (topic single source of truth)

Revision ID: a6b1c3d5e7f9
Revises: f7a3c9e25b41
Create Date: 2026-10-07 12:00:00.000000

题库三层收敛（主题→篇目→句子）：
- 篇目主题改为派生自所属单元（crud.derive_passage_topic：挂单元时
  create/update 一律以 unit.topic 为准）；
- 本迁移把存量挂单元篇目的 topic 回填为单元主题，使历史数据满足新不变式；
  未挂单元的老篇目 topic 保持原值不动（自主练习问答配对继续可用）。
"""

from alembic import op

revision = "a6b1c3d5e7f9"
down_revision = "f7a3c9e25b41"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE passage
        SET topic = unit.topic
        FROM unit
        WHERE passage.unit_id = unit.id
          AND passage.topic IS DISTINCT FROM unit.topic
        """
    )


def downgrade():
    # 回填不可逆：无法还原各篇目旧主题值，降级为空操作
    pass
