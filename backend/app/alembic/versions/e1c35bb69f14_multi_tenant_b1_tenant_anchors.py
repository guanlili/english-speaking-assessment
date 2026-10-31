"""multi-tenant b1 tenant anchors

Revision ID: e1c35bb69f14
Revises: cd998bb309d9
Create Date: 2026-10-31 09:09:48.100074

多租户 B1：tenant 表 + 默认租户种子 + user/classroom/student 三锚点表
tenant_id（NOT NULL + 列级 server_default 固定 UUID——回填存量且增量漏写
不可能）+ 校内复合唯一（旧全局唯一索引单校窗口内等价，收紧期随登录改造
移除）。设计依据 docs/multi-tenant-design.md §4/§9-2。
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'e1c35bb69f14'
down_revision = 'cd998bb309d9'
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    op.create_table(
        'tenant',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column('name_zh', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column('name_en', sqlmodel.sql.sqltypes.AutoString(length=120), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('timezone', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tenant_slug'), 'tenant', ['slug'], unique=True)
    op.create_index(op.f('ix_tenant_status'), 'tenant', ['status'], unique=False)
    # 默认租户须先于锚点列落库：server_default 回填的存量行要过 FK 检查。
    # 名称是占位（原校标识须由管理员核实后改名，V1.0 §6-1）。
    op.execute(
        "INSERT INTO tenant (id, slug, name_zh, status, timezone, created_at) "
        f"VALUES ('{DEFAULT_TENANT_ID}', 'default', '默认学校（待核实改名）', "
        "'active', 'Asia/Shanghai', now())"
    )
    for table in ('classroom', 'student', 'user'):
        op.add_column(
            table,
            sa.Column(
                'tenant_id',
                sa.Uuid(),
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
                nullable=False,
            ),
        )
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False)
        op.create_foreign_key(
            f'fk_{table}_tenant', table, 'tenant', ['tenant_id'], ['id']
        )
    op.create_unique_constraint('uq_user_tenant_username', 'user', ['tenant_id', 'username'])
    op.create_unique_constraint('uq_user_tenant_email', 'user', ['tenant_id', 'email'])


def downgrade():
    op.drop_constraint('uq_user_tenant_email', 'user', type_='unique')
    op.drop_constraint('uq_user_tenant_username', 'user', type_='unique')
    for table in ('user', 'student', 'classroom'):
        op.drop_constraint(f'fk_{table}_tenant', table, type_='foreignkey')
        op.drop_index(op.f(f'ix_{table}_tenant_id'), table=table)
        op.drop_column(table, 'tenant_id')
    op.drop_index(op.f('ix_tenant_status'), table='tenant')
    op.drop_index(op.f('ix_tenant_slug'), table='tenant')
    op.drop_table('tenant')
