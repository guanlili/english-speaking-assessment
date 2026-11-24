"""add vocabulary placement result history

Revision ID: a1b2c3d4e5f6
Revises: ac4d5e6f7a80
Create Date: 2026-11-24 12:00:00.000000

粗分档自适应小测（placement）结果历史表 + 进行中轮次唯一索引。

- additive：只新增 ``vocab_placement_result``；不回填、不改写既有
  VocabularyAnswer / 首答统计 / FSRS 状态 / 农场 XP。结果表与学生等级字段物理
  隔离，不回写 ``student.current_band``。
- 进行中 placement 轮：每学生至多一个（部分唯一索引，与 self/review/review_fsrs
  分列）；结束后退出索引谓词，允许重测开新一轮。
- 多租户 C4a 同口径：ENABLE + FORCE RLS + ``tenant_isolation`` 策略
  （缺上下文 NULL/'' 永不匹配，默认拒绝）。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "ac4d5e6f7a80"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
RESULT_TABLE = "vocab_placement_result"


def upgrade():
    op.create_table(
        RESULT_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("recommended_band", sa.String(length=16), nullable=False),
        sa.Column("recommended_level", sa.String(length=16), nullable=True),
        sa.Column("recommended_book_id", sa.Uuid(), nullable=True),
        sa.Column("recommended_book_title", sa.String(length=255), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "limitation",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
            server_default="none",
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["classroom_id"], ["classroom.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["vocabulary_session.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["recommended_book_id"], ["vocabulary_book.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_placement_result_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vocab_placement_result_tenant_id",
        RESULT_TABLE,
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_placement_result_classroom_id",
        RESULT_TABLE,
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_placement_result_student_id",
        RESULT_TABLE,
        ["student_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_placement_result_session_id",
        RESULT_TABLE,
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_placement_result_band",
        RESULT_TABLE,
        ["recommended_band"],
        unique=False,
    )

    # 进行中 placement 轮：每学生至多一个（与 self/review/review_fsrs 分列）
    op.create_index(
        "uq_vocab_session_placement_active",
        "vocabulary_session",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text(
            "assignment_id IS NULL AND kind = 'placement' AND status = 'in_progress'"
        ),
    )

    # 多租户 RLS（与既有业务表同口径）
    op.execute(f"ALTER TABLE {RESULT_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {RESULT_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {RESULT_TABLE} "
        "USING (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text) "
        "WITH CHECK (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text)"
    )


def downgrade():
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {RESULT_TABLE}")
    op.execute(f"ALTER TABLE {RESULT_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {RESULT_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("uq_vocab_session_placement_active", table_name="vocabulary_session")
    op.drop_index("ix_vocab_placement_result_band", table_name=RESULT_TABLE)
    op.drop_index("ix_vocab_placement_result_session_id", table_name=RESULT_TABLE)
    op.drop_index("ix_vocab_placement_result_student_id", table_name=RESULT_TABLE)
    op.drop_index("ix_vocab_placement_result_classroom_id", table_name=RESULT_TABLE)
    op.drop_index("ix_vocab_placement_result_tenant_id", table_name=RESULT_TABLE)
    op.drop_table(RESULT_TABLE)
