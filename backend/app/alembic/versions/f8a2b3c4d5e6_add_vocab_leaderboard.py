"""add vocabulary class leaderboard

Revision ID: f8a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-11-25 12:00:00.000000

additive：班内词汇学习榜两张表——

- ``vocabulary_leaderboard_setting``：课堂级开关 / 可见范围 / 匿名口径
  （一班一行；无行时服务层返回默认值，不写种子）；
- ``vocabulary_leaderboard_participant``：学生参与档案与班内稳定匿名编号
  （unique classroom×student、unique classroom×alias_no）。

两张表与既有业务表同口径 ENABLE + FORCE RLS + ``tenant_isolation`` 策略；
删除课堂由外键 CASCADE 清理参与者与设置行。downgrade 丢弃本批新增的
榜单配置与参与档案，不影响任何作答记录与 FSRS 状态。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "f8a2b3c4d5e6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

POLICY = (
    "coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text"
)


def upgrade():
    op.create_table(
        "vocabulary_leaderboard_setting",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "audience",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="teachers",
            nullable=False,
        ),
        sa.Column(
            "anonymous",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="uq_vocab_leaderboard_setting_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "classroom_id", name="uq_vocab_leaderboard_setting_classroom"
        ),
    )
    op.create_index(
        "ix_vocab_leaderboard_setting_tenant_id",
        "vocabulary_leaderboard_setting",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_leaderboard_setting_classroom_id",
        "vocabulary_leaderboard_setting",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_leaderboard_setting_updated_by",
        "vocabulary_leaderboard_setting",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "vocabulary_leaderboard_participant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("alias_no", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["student.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="uq_vocab_leaderboard_participant_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "classroom_id",
            "student_id",
            name="uq_vocab_leaderboard_participant_student",
        ),
        sa.UniqueConstraint(
            "classroom_id",
            "alias_no",
            name="uq_vocab_leaderboard_participant_alias",
        ),
    )
    op.create_index(
        "ix_vocab_leaderboard_participant_tenant_id",
        "vocabulary_leaderboard_participant",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_leaderboard_participant_classroom_id",
        "vocabulary_leaderboard_participant",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_leaderboard_participant_student_id",
        "vocabulary_leaderboard_participant",
        ["student_id"],
        unique=False,
    )

    # 多租户 C4a 同口径：ENABLE + FORCE RLS + tenant_isolation 策略
    # （缺上下文 NULL/'' 永不匹配，默认拒绝；与既有业务表一致）。
    for table in (
        "vocabulary_leaderboard_setting",
        "vocabulary_leaderboard_participant",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({POLICY}) WITH CHECK ({POLICY})"
        )


def downgrade():
    for table in (
        "vocabulary_leaderboard_participant",
        "vocabulary_leaderboard_setting",
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_vocab_leaderboard_participant_student_id",
        table_name="vocabulary_leaderboard_participant",
    )
    op.drop_index(
        "ix_vocab_leaderboard_participant_classroom_id",
        table_name="vocabulary_leaderboard_participant",
    )
    op.drop_index(
        "ix_vocab_leaderboard_participant_tenant_id",
        table_name="vocabulary_leaderboard_participant",
    )
    op.drop_table("vocabulary_leaderboard_participant")
    op.drop_index(
        "ix_vocab_leaderboard_setting_updated_by",
        table_name="vocabulary_leaderboard_setting",
    )
    op.drop_index(
        "ix_vocab_leaderboard_setting_classroom_id",
        table_name="vocabulary_leaderboard_setting",
    )
    op.drop_index(
        "ix_vocab_leaderboard_setting_tenant_id",
        table_name="vocabulary_leaderboard_setting",
    )
    op.drop_table("vocabulary_leaderboard_setting")
