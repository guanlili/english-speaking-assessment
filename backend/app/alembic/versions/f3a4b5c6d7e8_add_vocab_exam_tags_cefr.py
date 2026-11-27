"""add exam tags and CEFR band to vocab word/level entry (#517)

Revision ID: f3a4b5c6d7e8
Revises: d8e9f0a1b2c3
Create Date: 2026-11-25

两张词条表各加：
- ``exam_tags``：多选考试标签 JSON（SAT/ACT/GRE/CET4/IELTS/TOEFL），非空，
  存量行回填空列表；
- ``cefr_band``：A1–C2 档位，nullable；存量行保持 NULL，不伪造 CEFR 评定。

只加字段，不删列、不改既有列可空性；CEFR 仅为内容标签，不是测评结论。
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "f3a4b5c6d7e8"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vocabulary_word",
        sa.Column(
            "exam_tags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "vocabulary_word",
        sa.Column(
            "cefr_band",
            sqlmodel.sql.sqltypes.AutoString(length=8),
            nullable=True,
        ),
    )
    op.add_column(
        "vocab_level_entry",
        sa.Column(
            "exam_tags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "vocab_level_entry",
        sa.Column(
            "cefr_band",
            sqlmodel.sql.sqltypes.AutoString(length=8),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("vocab_level_entry", "cefr_band")
    op.drop_column("vocab_level_entry", "exam_tags")
    op.drop_column("vocabulary_word", "cefr_band")
    op.drop_column("vocabulary_word", "exam_tags")
