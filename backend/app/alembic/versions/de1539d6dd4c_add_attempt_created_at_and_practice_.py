"""add attempt created_at and practice_session session_date indexes

Revision ID: de1539d6dd4c
Revises: 15afa49a7c10
Create Date: 2026-10-26

大盘区间聚合与日快照回算的时间列索引：attempt 只有 status 打头的复合
索引（纯时间条件不可用），practice_session 的索引全部 student_id 打头
（纯日期条件不可用）。注：autogenerate 同时探测到本机开发库
admin_metrics_daily.updated_at 为 NOT NULL（迁移链与模型均为 nullable），
属本机库局部漂移，不迁就、已从迁移中剔除。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'de1539d6dd4c'
down_revision = '15afa49a7c10'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_attempt_created_at', 'attempt', ['created_at'], unique=False)
    op.create_index('ix_practice_session_session_date', 'practice_session', ['session_date'], unique=False)


def downgrade():
    op.drop_index('ix_practice_session_session_date', table_name='practice_session')
    op.drop_index('ix_attempt_created_at', table_name='attempt')
