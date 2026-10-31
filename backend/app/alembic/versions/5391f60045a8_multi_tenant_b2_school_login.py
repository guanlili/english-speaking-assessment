"""multi-tenant b2 school login

Revision ID: 5391f60045a8
Revises: e1c35bb69f14
Create Date: 2026-10-31 09:41:00

多租户 B2：登录租户解析配套——user.username/email 的全局唯一索引降为
普通索引，唯一性完全由 B1 的 (tenant_id, X) 复合唯一承接（两校可同号/
同邮箱）。单校窗口内两者等价，故随迁移同步落地无行为差异；无租户限定
的全局登录查找在命中多行时按「账号或密码不正确」拒绝（crud 层处理）。
设计依据 docs/multi-tenant-design.md §4.3/§5.1。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5391f60045a8'
down_revision = 'e1c35bb69f14'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index(op.f('ix_user_email'), table_name='user')
    op.create_index(op.f('ix_user_email'), 'user', ['email'], unique=False)
    op.drop_index(op.f('ix_user_username'), table_name='user')
    op.create_index(op.f('ix_user_username'), 'user', ['username'], unique=False)


def downgrade():
    # 回滚前提：user 表内无跨租户重号/重邮箱（多校写入后禁回滚，V1.0 §6-6）
    op.drop_index(op.f('ix_user_username'), table_name='user')
    op.create_index(
        op.f('ix_user_username'), 'user', ['username'], unique=True,
        postgresql_where=sa.text('tenant_id = \'00000000-0000-0000-0000-000000000001\''),
    )
    op.drop_index(op.f('ix_user_email'), table_name='user')
    op.create_index(
        op.f('ix_user_email'), 'user', ['email'], unique=True,
        postgresql_where=sa.text('tenant_id = \'00000000-0000-0000-0000-000000000001\''),
    )
