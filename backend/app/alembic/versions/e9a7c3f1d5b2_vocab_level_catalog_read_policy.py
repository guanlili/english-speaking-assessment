"""vocab level catalog is readable by every tenant

Revision ID: e9a7c3f1d5b2
Revises: c7e2a9f4b1d8
Create Date: 2026-11-24 16:10:00

五级词库是平台授权目录：学校侧只读选词，写入仅平台运营。
C4a 的 tenant_isolation 会把它按租户隔离，学校会话看不到 default 租户
导入的 10k+ 词条，导致「按级别选词 / 从五级词库转入 / 词条级别标注」
全部为空（本地隔离环境已复现）。

本迁移只给 vocab_level_entry 增加一条 FOR SELECT 的宽松策略：
- SELECT 全表可读（平台授权目录语义）；
- INSERT/UPDATE/DELETE 仍只受 tenant_isolation 约束，学校不能跨租户写；
- 不是 BYPASSRLS，不改变其它表的隔离。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "e9a7c3f1d5b2"
down_revision = "c7e2a9f4b1d8"
branch_labels = None
depends_on = None

POLICY_NAME = "vocab_level_catalog_read"


def upgrade() -> None:
    op.execute(
        f"CREATE POLICY {POLICY_NAME} ON vocab_level_entry FOR SELECT USING (true)"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON vocab_level_entry")
