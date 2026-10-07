"""drop wordlist_entry（老 A2/B1/B2 词表整表退役）

Revision ID: b7e2d4c9a1f3
Revises: f7a3c9e25b41
Create Date: 2026-10-07 21:30:00.000000

五级词库统一（PR#77）后的收尾：导入端点已 410、启动种子已删、
管理页已下线，本表唯一写入路径只剩种子——整表删除。

- 历史 attempt.vocab 中的旧口径 JSON 由 attempt 表原样保留（不回填不重算）；
- 若需回滚到退役前状态，downgrade 会重建空表（原数据不可恢复，
  退役前的备份里有 pg_dump 快照）。
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes as sqltypes
from alembic import op

revision = "b7e2d4c9a1f3"
down_revision = "a6b1c3d5e7f9"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index(op.f("ix_wordlist_entry_lemma"), table_name="wordlist_entry")
    op.drop_index(op.f("ix_wordlist_entry_band"), table_name="wordlist_entry")
    op.drop_table("wordlist_entry")


def downgrade():
    op.create_table(
        "wordlist_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lemma", sqltypes.AutoString(length=64), nullable=False),
        sa.Column("band", sqltypes.AutoString(length=10), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_wordlist_entry_band"), "wordlist_entry", ["band"], unique=False
    )
    op.create_index(
        op.f("ix_wordlist_entry_lemma"), "wordlist_entry", ["lemma"], unique=True
    )
