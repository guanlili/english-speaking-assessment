"""vocab student session active uniqueness

Revision ID: c9a4f1d2e8b3
Revises: e7a528475a53
Create Date: 2026-10-06 12:40:00.000000

自主/复习轮并发开轮的数据库级兜底（评审 P2）：
- uq_vocab_session_self_active：每学生每词库至多一个进行中自主轮；
- uq_vocab_session_review_active：每学生至多一个进行中复习轮。
轮次提交后退出索引谓词，不阻止「再来一轮」。

注意：若旧版本并发缺陷已在库中留下重复的进行中自主/复习轮，创建唯一
索引会失败并列出重复组；需先人工归并（保留最早一轮、结束其余）再升级。
该功能未上线，正常环境不会出现重复。
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9a4f1d2e8b3"
down_revision = "e7a528475a53"
branch_labels = None
depends_on = None

SELF_PREDICATE = "assignment_id IS NULL AND kind = 'self' AND status = 'in_progress'"
REVIEW_PREDICATE = "assignment_id IS NULL AND kind = 'review' AND status = 'in_progress'"


def _duplicate_groups(bind, predicate: str) -> list[tuple]:
    return bind.execute(
        sa.text(
            "SELECT student_id, coalesce(source_book_id::text, ''), count(*) "
            f"FROM vocabulary_session WHERE {predicate} "
            "GROUP BY 1, 2 HAVING count(*) > 1"
        )
    ).all()


def upgrade():
    conn = op.get_bind()
    dupes = _duplicate_groups(conn, SELF_PREDICATE) + _duplicate_groups(
        conn, REVIEW_PREDICATE
    )
    if dupes:
        detail = "; ".join(
            f"student={row[0]} book={row[1]} count={row[2]}" for row in dupes
        )
        raise RuntimeError(
            "vocabulary_session 存在重复的进行中自主/复习轮（旧版并发缺陷遗留），"
            f"无法创建唯一索引：{detail}。请先人工归并（保留最早一轮、结束其余）后重试。"
        )
    op.create_index(
        "uq_vocab_session_self_active",
        "vocabulary_session",
        ["student_id", "source_book_id"],
        unique=True,
        postgresql_where=sa.text(SELF_PREDICATE),
    )
    op.create_index(
        "uq_vocab_session_review_active",
        "vocabulary_session",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text(REVIEW_PREDICATE),
    )


def downgrade():
    # 无损：只删本迁移创建的索引（并发保护退回应用层查询，非唯一兜底）
    op.drop_index(
        "uq_vocab_session_review_active",
        table_name="vocabulary_session",
        postgresql_where=sa.text(REVIEW_PREDICATE),
    )
    op.drop_index(
        "uq_vocab_session_self_active",
        table_name="vocabulary_session",
        postgresql_where=sa.text(SELF_PREDICATE),
    )
