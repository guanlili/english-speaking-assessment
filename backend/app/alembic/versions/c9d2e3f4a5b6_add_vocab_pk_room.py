"""add vocabulary classroom PK room tables (room code / whole-class)

Revision ID: c9d2e3f4a5b6
Revises: e5b711a3c9d2
Create Date: 2026-11-29 10:00:00.000000

#619 课堂大屏 PK「房间码」形态：房间 / 参赛者 / 作答三张独立表，与既有
1v1 排队 PK（vocab_pk_*）并存互不影响。

- 口径隔离：作答只落 ``vocab_pk_room_answer``，不写 ``vocabulary_answer``、
  不改任务首答统计、不写错词本、进不了 FSRS；downgrade 只丢弃房间数据。
- 多租户同口径：ENABLE + FORCE RLS + ``tenant_isolation`` 策略。
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "c9d2e3f4a5b6"
down_revision = "e5b711a3c9d2"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

ROOM_TABLES = [
    "vocab_pk_room",
    "vocab_pk_room_player",
    "vocab_pk_room_answer",
]


def _tenant_column():
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        nullable=False,
        server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
    )


def upgrade():
    op.create_table(
        "vocab_pk_room",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_column(),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column(
            "room_code", sqlmodel.sql.sqltypes.AutoString(length=6), nullable=False
        ),
        sa.Column(
            "mode",
            sqlmodel.sql.sqltypes.AutoString(length=8),
            server_default="solo",
            nullable=False,
        ),
        sa.Column("team_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_types", sa.JSON(), nullable=False),
        sa.Column(
            "question_count", sa.Integer(), server_default="10", nullable=False
        ),
        sa.Column(
            "per_question_seconds", sa.Integer(), server_default="20", nullable=False
        ),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="waiting",
            nullable=False,
        ),
        sa.Column("snapshot_items", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["book_id"], ["vocabulary_book.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], name="fk_vocab_pk_room_tenant"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_code", name="uq_vocab_pk_room_code"),
    )
    op.create_index(
        "ix_vocab_pk_room_tenant_id", "vocab_pk_room", ["tenant_id"]
    )
    op.create_index(
        "ix_vocab_pk_room_classroom_id", "vocab_pk_room", ["classroom_id"]
    )
    op.create_index("ix_vocab_pk_room_book_id", "vocab_pk_room", ["book_id"])
    op.create_index(
        "ix_vocab_pk_room_class_status",
        "vocab_pk_room",
        ["classroom_id", "status"],
    )

    op.create_table(
        "vocab_pk_room_player",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_column(),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("team_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("answered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["room_id"], ["vocab_pk_room.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_pk_room_player_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id", "student_id", name="uq_vocab_pk_room_player_room_student"
        ),
    )
    op.create_index(
        "ix_vocab_pk_room_player_tenant_id", "vocab_pk_room_player", ["tenant_id"]
    )
    op.create_index(
        "ix_vocab_pk_room_player_room_id", "vocab_pk_room_player", ["room_id"]
    )
    op.create_index(
        "ix_vocab_pk_room_player_classroom_id",
        "vocab_pk_room_player",
        ["classroom_id"],
    )
    op.create_index(
        "ix_vocab_pk_room_player_student_id", "vocab_pk_room_player", ["student_id"]
    )

    op.create_table(
        "vocab_pk_room_answer",
        sa.Column("id", sa.Uuid(), nullable=False),
        _tenant_column(),
        sa.Column("room_id", sa.Uuid(), nullable=False),
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
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("base_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("speed_bonus", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["room_id"], ["vocab_pk_room.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["player_id"], ["vocab_pk_room_player.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocab_pk_room_answer_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id", "item_index", name="uq_vocab_pk_room_answer_slot"
        ),
    )
    op.create_index(
        "ix_vocab_pk_room_answer_tenant_id", "vocab_pk_room_answer", ["tenant_id"]
    )
    op.create_index(
        "ix_vocab_pk_room_answer_room_id", "vocab_pk_room_answer", ["room_id"]
    )
    op.create_index(
        "ix_vocab_pk_room_answer_player_id",
        "vocab_pk_room_answer",
        ["player_id"],
    )
    op.create_index(
        "ix_vocab_pk_room_answer_student_id",
        "vocab_pk_room_answer",
        ["student_id"],
    )

    for table in ROOM_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text) "
            "WITH CHECK (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text)"
        )


def downgrade():
    for table in reversed(ROOM_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
