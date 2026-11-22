"""add vocabulary focus farm plot

Revision ID: e8c2f6a1b9d4
Revises: f1a2b3c4d5e6
Create Date: 2026-11-22 18:00:00.000000

第三批「专注农场」地块表（按登录账号跨班连续）。

- additive：只新增 ``vocab_farm_plot``；不回填、不改写既有 VocabularyAnswer /
  错词历史计数 / 历史 session 快照；downgrade 丢弃农场地块，不影响首答统计。
- 激励边界：收获 XP 写既有 ``student.xp``，徽章落既有 ``student_badge`` 表；
  本迁移不新增并行积分字段/表。
- 多租户 C4a 同口径：ENABLE + FORCE RLS + ``tenant_isolation`` 策略
  （缺上下文 NULL/'' 永不匹配，默认拒绝）。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "e8c2f6a1b9d4"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

FARM_TABLE = "vocab_farm_plot"


def upgrade():
    op.create_table(
        FARM_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "growth_points", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "today_points", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("last_points_date", sa.Date(), nullable=True),
        sa.Column(
            "today_farm_xp", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("last_farm_xp_date", sa.Date(), nullable=True),
        sa.Column(
            "harvest_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("last_harvested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_farm_plot_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_vocab_farm_plot_user"),
    )
    op.create_index(
        "ix_vocab_farm_plot_tenant_id",
        FARM_TABLE,
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_farm_plot_user_id",
        FARM_TABLE,
        ["user_id"],
        unique=False,
    )

    # 多租户 RLS（与既有业务表同口径）
    op.execute(f"ALTER TABLE {FARM_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {FARM_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {FARM_TABLE} "
        "USING (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text) "
        "WITH CHECK (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text)"
    )


def downgrade():
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {FARM_TABLE}")
    op.execute(f"ALTER TABLE {FARM_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {FARM_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_vocab_farm_plot_user_id", table_name=FARM_TABLE)
    op.drop_index("ix_vocab_farm_plot_tenant_id", table_name=FARM_TABLE)
    op.drop_table(FARM_TABLE)
