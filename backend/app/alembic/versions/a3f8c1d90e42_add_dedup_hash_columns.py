"""add dedup hash columns for question bank matching

Revision ID: a3f8c1d90e42
Revises: d6f4f6c56218
Create Date: 2026-10-20 11:05:00.000000

题库查重预计算列（services/content_dedup.py 维护）。存量行在此回填：
归一化函数是 app/services/content_dedup.py norm_text 的冻结拷贝——
迁移一经合入不可再改（历史不漂移），后续语义演进只影响新写入并由
读取侧的 NULL 回退兜底。
"""
import hashlib
import unicodedata

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f8c1d90e42"
down_revision = "d6f4f6c56218"
branch_labels = None
depends_on = None

# (表名, [(原文列, 哈希列), ...])——与 models.py / content_dedup._DEDUP_FIELDS 对应
TABLES: list[tuple[str, list[tuple[str, str]]]] = [
    ("passage", [("title", "dedup_title_hash"), ("text", "dedup_text_hash")]),
    ("unit", [("title", "dedup_title_hash")]),
    ("scenario", [("topic", "dedup_topic_hash")]),
    ("scenario_question", [("text", "dedup_text_hash")]),
    ("repeat_sentence", [("text", "dedup_text_hash")]),
    ("instruction", [("text", "dedup_text_hash")]),
]


def _frozen_norm(raw: object) -> str:
    """content_dedup.norm_text 的冻结拷贝（NFKC + strip + casefold + 空白折叠）。"""
    if raw is None:
        return ""
    return " ".join(
        unicodedata.normalize("NFKC", str(raw)).strip().casefold().split()
    )


def _frozen_hash(raw: object) -> str:
    return hashlib.sha256(_frozen_norm(raw).encode("utf-8")).hexdigest()


def upgrade():
    bind = op.get_bind()
    for table, cols in TABLES:
        for src, dst in cols:
            op.add_column(
                table, sa.Column(dst, sa.String(length=64), nullable=True)
            )
            rows = bind.execute(sa.text(f"SELECT id, {src} FROM {table}"))
            updates = [
                {"h": _frozen_hash(value), "id": str(row_id)}
                for row_id, value in rows
            ]
            rows.close()
            if updates:
                bind.execute(
                    sa.text(f"UPDATE {table} SET {dst} = :h WHERE id = :id"),
                    updates,
                )
            op.create_index(
                f"ix_{table}_{dst}", table, [dst], unique=False
            )


def downgrade():
    for table, cols in TABLES:
        for src, dst in cols:
            op.drop_index(f"ix_{table}_{dst}", table_name=table)
            op.drop_column(table, dst)
