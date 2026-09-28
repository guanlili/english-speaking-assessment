"""add missing constraints and indexes

补齐模型声明但迁移缺失的约束/索引（原 1800e09cea00 / eec39eea422c 为空操作）：
- attempt.idempotency_key 唯一约束：并发重传不重复创建作答/扣费
- student 显示名唯一约束 + 部分唯一索引：同名加入防重复（join_classroom 依赖）
- attempt.student_id / session_id 索引：board/trail/today/gamification 高频过滤

上述约束此前从未在生产生效，并发同名/重传可能已留下重复行；建约束前先清理，
否则 create_unique_constraint 会失败并导致部署流水线整体回滚。

Revision ID: 14046ec75466
Revises: eec39eea422c
Create Date: 2026-09-28 10:34:32.486465

"""
import random
from collections import defaultdict

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "14046ec75466"
down_revision = "eec39eea422c"
branch_labels = None
depends_on = None


def _dedup_idempotency_keys() -> None:
    """重复的 idempotency_key：保留最早一条，其余置 NULL。"""
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY idempotency_key ORDER BY created_at, id
          ) AS rn
          FROM attempt
          WHERE idempotency_key IS NOT NULL
        )
        UPDATE attempt SET idempotency_key = NULL
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )


def _dedup_student_names() -> None:
    """同名学生去重：保留最早一条的 suffix，其余分配唯一 4 位 suffix。

    并发同名加入在唯一约束缺失时可能留下重复（多个 NULL suffix 或 suffix
    碰撞）。建约束前清理，确保 (classroom_id, display_name, suffix) 唯一。
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, classroom_id, display_name, suffix FROM student "
            "ORDER BY classroom_id, display_name, created_at, id"
        )
    ).fetchall()
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row[1], row[2])].append(row)
    for members in groups.values():
        used: set = set()
        for index, member in enumerate(members):
            student_id, _classroom, _name, suffix = member
            if index == 0:
                used.add(suffix)
                continue
            if suffix is None or suffix in used:
                while True:
                    candidate = f"{random.randint(1000, 9999)}"
                    if candidate not in used:
                        break
                bind.execute(
                    sa.text("UPDATE student SET suffix = :suffix WHERE id = :id"),
                    {"suffix": candidate, "id": student_id},
                )
                used.add(candidate)
            else:
                used.add(suffix)


def upgrade() -> None:
    _dedup_idempotency_keys()
    _dedup_student_names()
    # 原非唯一索引与唯一约束重复，先删除
    op.drop_index(op.f("ix_attempt_idempotency_key"), table_name="attempt")
    op.create_index(
        op.f("ix_attempt_session_id"), "attempt", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_attempt_student_id"), "attempt", ["student_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_attempt_idempotency_key", "attempt", ["idempotency_key"]
    )
    op.create_index(
        "ix_student_classroom_display_name_no_suffix",
        "student",
        ["classroom_id", "display_name"],
        unique=True,
        postgresql_where=sa.text("suffix IS NULL"),
    )
    op.create_unique_constraint(
        "uq_student_name_suffix", "student", ["classroom_id", "display_name", "suffix"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_student_name_suffix", "student", type_="unique")
    op.drop_index(
        "ix_student_classroom_display_name_no_suffix",
        table_name="student",
        postgresql_where=sa.text("suffix IS NULL"),
    )
    op.drop_constraint("uq_attempt_idempotency_key", "attempt", type_="unique")
    op.drop_index(op.f("ix_attempt_student_id"), table_name="attempt")
    op.drop_index(op.f("ix_attempt_session_id"), table_name="attempt")
    op.create_index(
        op.f("ix_attempt_idempotency_key"), "attempt", ["idempotency_key"], unique=False
    )
