"""add attempt.audio_purged_at (audio retention progress marker)

Revision ID: a3f1d90c2b47
Revises: 58ae71ae560e
Create Date: 2026-10-09 05:20:00.000000

音频保留期清理推进标记（wise-quarry-trout 批次06）：
- attempt.audio_purged_at：文件被 TTL 清理删除或结算（文件本就缺失/
  路径越界/指向 content 标准音）的时刻；NULL = 尚未处理。
- 此前清理只删文件不记录状态：候选超过单轮 limit(500) 后，下一轮仍
  选中同一批已删记录，清理永远停在第一批。有标记后按 (created_at, id)
  稳定分批推进。
- 历史行全部为 NULL（未处理），行为兼容：TTL=0 时清理模块整体不启用，
  本列不影响任何读写路径。
"""

import sqlalchemy as sa
from alembic import op

revision = "a3f1d90c2b47"
down_revision = "58ae71ae560e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "attempt",
        sa.Column("audio_purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("attempt", "audio_purged_at")
