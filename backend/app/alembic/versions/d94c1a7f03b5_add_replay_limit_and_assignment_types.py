"""add replay limit and assignment types

Revision ID: d94c1a7f03b5
Revises: b7d2e8f41a9c
Create Date: 2026-09-28 15:00:00.000000

三种题型体系：复述句可重听次数（默认 3）、课堂题型指派（NULL=包含）、
听句播放计数表（学生×会话×题目，防刷）。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d94c1a7f03b5"
down_revision = "b7d2e8f41a9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 复述句：可重听次数（存量行回填默认 3）
    op.add_column(
        "repeat_sentence",
        sa.Column("replay_limit", sa.Integer(), nullable=False, server_default="3"),
    )

    # 课堂：题型指派三列（NULL=包含，默认三种全有）
    op.add_column("classroom", sa.Column("assign_reading", sa.Boolean(), nullable=True))
    op.add_column("classroom", sa.Column("assign_repeat", sa.Boolean(), nullable=True))
    op.add_column("classroom", sa.Column("assign_qa", sa.Boolean(), nullable=True))

    # 播放计数表
    op.create_table(
        "item_listen",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practice_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "student_id", "session_id", "item_id", name="uq_item_listen_scope"
        ),
    )


def downgrade() -> None:
    op.drop_table("item_listen")
    op.drop_column("classroom", "assign_qa")
    op.drop_column("classroom", "assign_repeat")
    op.drop_column("classroom", "assign_reading")
    op.drop_column("repeat_sentence", "replay_limit")
