"""multi-tenant b3 platform operator

Revision ID: a7c4d92e1f83
Revises: 5391f60045a8
Create Date: 2026-10-31 16:20:00

多租户 B3：平台运营独立身份 + 学校侧移除全局绕过。

1. 建 platform_operator 表（运营账号独立于学校 User，凭据走独立登录
   端点与独立 token audience：typ=operator/aud=platform）。
2. 存量 is_superuser=true 的学校账号统一落为校级 admin（role='admin'），
   不自动升级为跨校运营——运营种子由 init_db 按 FIRST_OPERATOR_* 幂等
   创建（默认沿用首超管凭据，单校过渡窗口）。
3. DROP user.is_superuser：自此学校侧不存在全局绕过身份，业务门禁
   一律认 role（设计稿 §3.2「不能只改 UI 名称」）。

downgrade 只恢复列与数据镜像，不删运营账号（账号由 init_db 管理）。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a7c4d92e1f83'
down_revision = '5391f60045a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'platform_operator',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_platform_operator_email'), 'platform_operator', ['email'], unique=True
    )
    # 先把全局超管语义收敛进 role，再删列（role 自 b7d2e8f41a9c 起存在）
    op.execute("UPDATE \"user\" SET role = 'admin' WHERE is_superuser = true")
    op.drop_column('user', 'is_superuser')


def downgrade():
    op.add_column(
        'user',
        sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    # 镜像恢复：校级 admin 还原为超管标志（单校窗口内语义等价）
    op.execute("UPDATE \"user\" SET is_superuser = true WHERE role = 'admin'")
    op.drop_index(
        op.f('ix_platform_operator_email'), table_name='platform_operator'
    )
    op.drop_table('platform_operator')
