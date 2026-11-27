"""add tenant module lifecycle (expires_at / grant_type / granted_by)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-24 13:00:00.000000

#517 A 部分：整校模块授权的租期/试用状态机。

- ``tenant_module`` 新增：
  - ``expires_at`` timestamptz 可空（空=长期；now >= expires_at 即 expired）；
  - ``grant_type`` varchar(16) 非空，``trial|paid|manual``，存量回填 ``manual``；
  - ``granted_by`` uuid 可空，FK ``platformoperator.id`` ON DELETE SET NULL。
- 开始时间复用既有 ``effective_at``，不新增重复的 starts_at 列。
- ``tenant_module_audit`` 新增 expires_at / grant_type / granted_by 的前后值列。
- ``expires_at`` 单列索引，支撑「N 天内到期」筛选。
- 不物理删除任何业务表/数据；downgrade 可逆（摘除新增列与索引）。

加列顺序：先加 nullable 列 → 回填 ``grant_type='manual'`` → 再设 NOT NULL +
server_default，避免存量行触发非空约束。
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

MODULE_TABLE = "tenant_module"
AUDIT_TABLE = "tenant_module_audit"

GRANTED_BY_FK = "fk_tenant_module_granted_by_platformoperator"
GRANTED_BY_IDX = "ix_tenant_module_granted_by"
EXPIRES_AT_IDX = "ix_tenant_module_expires_at"


def upgrade():
    # 1. 先加可空列（存量行不触发约束）
    op.add_column(
        MODULE_TABLE,
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        MODULE_TABLE,
        sa.Column("grant_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        MODULE_TABLE,
        sa.Column("granted_by", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        GRANTED_BY_FK,
        MODULE_TABLE,
        "platformoperator",
        ["granted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(GRANTED_BY_IDX, MODULE_TABLE, ["granted_by"], unique=False)
    op.create_index(EXPIRES_AT_IDX, MODULE_TABLE, ["expires_at"], unique=False)

    # 2. 存量回填：既有授权行一律按手工开通（长期，无到期日）
    op.execute(
        "UPDATE tenant_module SET grant_type = 'manual' WHERE grant_type IS NULL"
    )

    # 3. 再收紧非空 + DB 层默认值（新行漏写时兜底 manual）
    op.alter_column(
        MODULE_TABLE,
        "grant_type",
        nullable=False,
        server_default="manual",
        type_=sa.String(length=16),
    )

    # 4. 审计表前后值（全部可空：老审计行没有这些口径）
    op.add_column(
        AUDIT_TABLE,
        sa.Column("expires_at_before", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        AUDIT_TABLE,
        sa.Column("expires_at_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        AUDIT_TABLE,
        sa.Column("grant_type_before", sa.String(length=16), nullable=True),
    )
    op.add_column(
        AUDIT_TABLE,
        sa.Column("grant_type_after", sa.String(length=16), nullable=True),
    )
    op.add_column(
        AUDIT_TABLE,
        sa.Column("granted_by_before", sa.Uuid(), nullable=True),
    )
    op.add_column(
        AUDIT_TABLE,
        sa.Column("granted_by_after", sa.Uuid(), nullable=True),
    )


def downgrade():
    op.drop_column(AUDIT_TABLE, "granted_by_after")
    op.drop_column(AUDIT_TABLE, "granted_by_before")
    op.drop_column(AUDIT_TABLE, "grant_type_after")
    op.drop_column(AUDIT_TABLE, "grant_type_before")
    op.drop_column(AUDIT_TABLE, "expires_at_after")
    op.drop_column(AUDIT_TABLE, "expires_at_before")

    op.drop_index(EXPIRES_AT_IDX, table_name=MODULE_TABLE)
    op.drop_index(GRANTED_BY_IDX, table_name=MODULE_TABLE)
    op.drop_constraint(GRANTED_BY_FK, MODULE_TABLE, type_="foreignkey")
    op.drop_column(MODULE_TABLE, "granted_by")
    op.drop_column(MODULE_TABLE, "grant_type")
    op.drop_column(MODULE_TABLE, "expires_at")
