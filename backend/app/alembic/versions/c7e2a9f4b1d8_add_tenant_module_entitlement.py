"""add tenant module entitlement

Revision ID: c7e2a9f4b1d8
Revises: e8c2f6a1b9d4
Create Date: 2026-11-23 12:00:00.000000

#516 / #517：整校 × 模块授权（逻辑隔离，不拆库、不改业务表结构）。

- 新增 ``tenant_module``：``tenant_id × module_key`` 唯一一行；
  ``module_key ∈ {speaking, vocabulary}``；``enabled`` / ``updated_by`` /
  ``updated_at`` / ``effective_at``（可空=立即生效）。缺行 = 未购买（默认关）。
- 新增 ``tenant_module_audit``：运营改写授权的前后值、操作人、时间留痕。
- 存量回填：**speaking=on、vocabulary=off**（保口语现状可用，词汇默认不可见）；
  新租户不自动插行（缺行即 off）。回填幂等（ON CONFLICT DO NOTHING）。
- RLS 与既有业务表同口径；平台运营通道 BYPASSRLS 读写，学校侧只读本校行。
- downgrade 两张表一并摘除；回填数据随表丢弃，不影响任何业务作答数据。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "c7e2a9f4b1d8"
down_revision = "e8c2f6a1b9d4"
branch_labels = None
depends_on = None

MODULE_TABLE = "tenant_module"
AUDIT_TABLE = "tenant_module_audit"

POLICY = (
    "coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text"
)


def upgrade():
    op.create_table(
        MODULE_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=16), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["platformoperator.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "module_key", name="uq_tenant_module_tenant_key"
        ),
    )
    op.create_index(
        "ix_tenant_module_tenant_id", MODULE_TABLE, ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_tenant_module_module_key", MODULE_TABLE, ["module_key"], unique=False
    )
    op.create_index(
        "ix_tenant_module_updated_by", MODULE_TABLE, ["updated_by"], unique=False
    )

    op.create_table(
        AUDIT_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("module_key", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("enabled_before", sa.Boolean(), nullable=True),
        sa.Column("enabled_after", sa.Boolean(), nullable=True),
        sa.Column("effective_at_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_at_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_operator_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["actor_operator_id"], ["platformoperator.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tenant_module_audit_tenant_id",
        AUDIT_TABLE,
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_module_audit_module_key",
        AUDIT_TABLE,
        ["module_key"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_module_audit_actor_operator_id",
        AUDIT_TABLE,
        ["actor_operator_id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_module_audit_action",
        AUDIT_TABLE,
        ["action"],
        unique=False,
    )

    # RLS（与既有业务表同口径；平台通道 BYPASSRLS）
    for table in (MODULE_TABLE, AUDIT_TABLE):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({POLICY}) WITH CHECK ({POLICY})"
        )

    # 存量回填：speaking=on（保在用口语不被锁死）、vocabulary=off（词汇默认
    # 不可见，试点校由运营后台或回填脚本按显式 slug 整校开启）。幂等重放安全。
    op.execute(
        text(
            f"""
            INSERT INTO {MODULE_TABLE}
                (id, tenant_id, module_key, enabled, updated_at, effective_at)
            SELECT gen_random_uuid(), t.id, 'speaking', true, now(), NULL
            FROM tenant t
            ON CONFLICT (tenant_id, module_key) DO NOTHING
            """
        )
    )
    op.execute(
        text(
            f"""
            INSERT INTO {MODULE_TABLE}
                (id, tenant_id, module_key, enabled, updated_at, effective_at)
            SELECT gen_random_uuid(), t.id, 'vocabulary', false, now(), NULL
            FROM tenant t
            ON CONFLICT (tenant_id, module_key) DO NOTHING
            """
        )
    )


def downgrade():
    for table in (AUDIT_TABLE, MODULE_TABLE):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index(
        "ix_tenant_module_audit_actor_operator_id", table_name=AUDIT_TABLE
    )
    op.drop_index("ix_tenant_module_audit_action", table_name=AUDIT_TABLE)
    op.drop_index("ix_tenant_module_audit_module_key", table_name=AUDIT_TABLE)
    op.drop_index("ix_tenant_module_audit_tenant_id", table_name=AUDIT_TABLE)
    op.drop_table(AUDIT_TABLE)

    op.drop_index("ix_tenant_module_updated_by", table_name=MODULE_TABLE)
    op.drop_index("ix_tenant_module_module_key", table_name=MODULE_TABLE)
    op.drop_index("ix_tenant_module_tenant_id", table_name=MODULE_TABLE)
    op.drop_table(MODULE_TABLE)
