"""vocab ai insights cache

Revision ID: e2c8b7a4d9f1
Revises: d7b3e9c4a1f2
Create Date: 2026-10-06 18:20:00.000000

AI 结果缓存表：按内容指纹判定新旧（数据变化即指纹变化，旧缓存标记
待更新）；downgrade 无损（只删表）。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "e2c8b7a4d9f1"
down_revision = "d7b3e9c4a1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vocabulary_ai_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cache_key", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["student.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vocabulary_ai_cache_kind"), "vocabulary_ai_cache", ["kind"]
    )
    op.create_index(
        op.f("ix_vocabulary_ai_cache_student_id"),
        "vocabulary_ai_cache",
        ["student_id"],
    )
    op.create_unique_constraint(
        op.f("uq_vocabulary_ai_cache_cache_key"),
        "vocabulary_ai_cache",
        ["cache_key"],
    )


def downgrade():
    op.drop_constraint(
        op.f("uq_vocabulary_ai_cache_cache_key"),
        "vocabulary_ai_cache",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_vocabulary_ai_cache_student_id"), table_name="vocabulary_ai_cache"
    )
    op.drop_index(
        op.f("ix_vocabulary_ai_cache_kind"), table_name="vocabulary_ai_cache"
    )
    op.drop_table("vocabulary_ai_cache")
