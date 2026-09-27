"""add session unique constraint

Revision ID: a3f5c8e21b7d
Revises: 2c7f71022d00
Create Date: 2026-09-27 09:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3f5c8e21b7d"
down_revision = "2c7f71022d00"
branch_labels = None
depends_on = None


def _dedupe_sessions() -> None:
    """建唯一索引前清理并发建轮 bug 可能遗留的重复会话。

    重复键 = (student_id, session_date, passage_id, mode)（passage_id 非空）。
    保留 created_at 最早的一行；重复行上的作答改挂到保留行；
    保留行未结算而重复行已结算时，把 stars 带过去（防重结算双倍 XP）；
    最后删除重复行。幂等：无重复时每条语句都是零行变更。
    """
    ranked = """
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY student_id, session_date, passage_id, mode
                   ORDER BY created_at NULLS LAST, id
               ) AS keep_id
        FROM practice_session
        WHERE passage_id IS NOT NULL
    """
    # 已结算的星数带到保留行，避免作答重挂后再次结算
    op.execute(
        f"""
        WITH ranked AS ({ranked})
        UPDATE practice_session keep
        SET stars = dup.stars
        FROM ranked r, practice_session dup
        WHERE keep.id = r.keep_id
          AND dup.id = r.id
          AND r.id <> r.keep_id
          AND keep.stars IS NULL
          AND dup.stars IS NOT NULL
        """
    )
    # 重复行上的作答改挂到保留行
    op.execute(
        f"""
        WITH ranked AS ({ranked})
        UPDATE attempt a
        SET session_id = r.keep_id
        FROM ranked r
        WHERE a.session_id = r.id AND r.id <> r.keep_id
        """
    )
    # 删除重复行
    op.execute(
        f"""
        WITH ranked AS ({ranked})
        DELETE FROM practice_session p
        USING ranked r
        WHERE p.id = r.id AND r.id <> r.keep_id
        """
    )


def upgrade() -> None:
    _dedupe_sessions()
    op.create_index(
        "ix_practice_session_unique",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode"],
        unique=True,
        postgresql_where=op.f("passage_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_practice_session_unique",
        table_name="practice_session",
        postgresql_where=op.f("passage_id IS NOT NULL"),
    )
