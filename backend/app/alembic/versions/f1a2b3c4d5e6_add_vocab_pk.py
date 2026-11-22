"""add vocabulary classroom PK tables

Revision ID: f1a2b3c4d5e6
Revises: d9a1b2c3e4f5
Create Date: 2026-11-22 16:00:00.000000

第三批「课堂实时 PK」独立表（大厅 / 对局 / 玩家 / 作答）。

- 口径分离：PK 作答只落 ``vocab_pk_answer``，不写 ``vocabulary_answer``、
  不改任务首答统计、不动发布快照；downgrade 只丢弃 PK 数据，历史任务与
  练习作答不受影响。
- 多租户 C4a 同口径：ENABLE + FORCE RLS + ``tenant_isolation`` 策略
  （缺上下文 NULL/'' 永不匹配，默认拒绝）。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "d9a1b2c3e4f5"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

PK_TABLES = [
    "vocab_pk_lobby",
    "vocab_pk_match",
    "vocab_pk_player",
    "vocab_pk_answer",
]


def upgrade():
    op.create_table(
        "vocab_pk_lobby",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_types", sa.JSON(), nullable=False),
        sa.Column(
            "question_count", sa.Integer(), server_default="8", nullable=False
        ),
        sa.Column(
            "per_question_seconds",
            sa.Integer(),
            server_default="20",
            nullable=False,
        ),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="open",
            nullable=False,
        ),
        sa.Column("snapshot_items", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["classroom_id"], ["classroom.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["book_id"], ["vocabulary_book.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_pk_lobby_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vocab_pk_lobby_tenant_id",
        "vocab_pk_lobby",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_lobby_classroom_id",
        "vocab_pk_lobby",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_lobby_book_id",
        "vocab_pk_lobby",
        ["book_id"],
        unique=False,
    )
    # 同一课堂至多一个开放大厅；历史关闭大厅可多条
    op.create_index(
        "uq_vocab_pk_lobby_open",
        "vocab_pk_lobby",
        ["classroom_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "vocab_pk_match",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("lobby_id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_items", sa.JSON(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("per_question_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "current_item_index", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("current_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "end_reason",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=True,
        ),
        sa.Column("winner_student_id", sa.Uuid(), nullable=True),
        sa.Column(
            "state_version", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lobby_id"], ["vocab_pk_lobby.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_pk_match_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vocab_pk_match_tenant_id",
        "vocab_pk_match",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_match_lobby_id",
        "vocab_pk_match",
        ["lobby_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_match_classroom_id",
        "vocab_pk_match",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_match_winner_student_id",
        "vocab_pk_match",
        ["winner_student_id"],
        unique=False,
    )

    op.create_table(
        "vocab_pk_player",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("lobby_id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=True),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("side", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="waiting",
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("answered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lobby_id"], ["vocab_pk_lobby.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["match_id"], ["vocab_pk_match.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_pk_player_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lobby_id", "student_id", name="uq_vocab_pk_player_lobby_student"
        ),
    )
    op.create_index(
        "ix_vocab_pk_player_tenant_id",
        "vocab_pk_player",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_player_lobby_id",
        "vocab_pk_player",
        ["lobby_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_player_match_id",
        "vocab_pk_player",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_player_classroom_id",
        "vocab_pk_player",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_player_student_id",
        "vocab_pk_player",
        ["student_id"],
        unique=False,
    )

    op.create_table(
        "vocab_pk_answer",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column(
            "prompt_type",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="meaning",
            nullable=False,
        ),
        sa.Column(
            "answer_raw",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "answer_normalized",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("base_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("speed_bonus", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "idempotency_key",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["vocab_pk_match.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["vocab_pk_player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_pk_answer_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id", "item_index", name="uq_vocab_pk_answer_slot"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_vocab_pk_answer_idempotency"
        ),
    )
    op.create_index(
        "ix_vocab_pk_answer_tenant_id",
        "vocab_pk_answer",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_answer_match_id",
        "vocab_pk_answer",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_answer_player_id",
        "vocab_pk_answer",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_pk_answer_student_id",
        "vocab_pk_answer",
        ["student_id"],
        unique=False,
    )

    # 多租户 RLS（与既有业务表同口径）
    for table in PK_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text) "
            "WITH CHECK (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text)"
        )


def downgrade():
    for table in reversed(PK_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("vocab_pk_answer")
    op.drop_table("vocab_pk_player")
    op.drop_table("vocab_pk_match")
    op.drop_table("vocab_pk_lobby")
