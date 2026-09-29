"""add immutable classroom exercise snapshots

Revision ID: 6f0d8c1a2b3c
Revises: c7e2d3a9f5b1
"""

from alembic import op
import sqlalchemy as sa


revision = "6f0d8c1a2b3c"
down_revision = "c7e2d3a9f5b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classroom_exercise",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("snapshot_items", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["classroom_id"], ["classroom.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "classroom_id", "version_no", name="uq_classroom_exercise_version"
        ),
    )
    op.create_index(
        "ix_classroom_exercise_classroom_id",
        "classroom_exercise",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        "ix_classroom_exercise_status",
        "classroom_exercise",
        ["status"],
        unique=False,
    )

    op.add_column("classroom", sa.Column("current_exercise_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_classroom_current_exercise_id",
        "classroom",
        ["current_exercise_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_classroom_current_exercise",
        "classroom",
        "classroom_exercise",
        ["current_exercise_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "practice_session", sa.Column("assignment_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        "ix_practice_session_assignment_id",
        "practice_session",
        ["assignment_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_practice_session_assignment",
        "practice_session",
        "classroom_exercise",
        ["assignment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("attempt", sa.Column("item_snapshot", sa.JSON(), nullable=True))

    op.drop_index("ix_practice_session_unique", table_name="practice_session")
    op.drop_index(
        "ix_practice_session_unique_null_passage", table_name="practice_session"
    )
    op.create_index(
        "ix_practice_session_unique",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode", "assignment_id"],
        unique=True,
        postgresql_where=sa.text(
            "passage_id IS NOT NULL AND assignment_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_practice_session_unique_legacy_passage",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode"],
        unique=True,
        postgresql_where=sa.text(
            "passage_id IS NOT NULL AND assignment_id IS NULL"
        ),
    )
    op.create_index(
        "ix_practice_session_unique_null_passage",
        "practice_session",
        ["student_id", "session_date", "mode", "assignment_id"],
        unique=True,
        postgresql_where=sa.text(
            "passage_id IS NULL AND assignment_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_practice_session_unique_null_passage_legacy",
        "practice_session",
        ["student_id", "session_date", "mode"],
        unique=True,
        postgresql_where=sa.text(
            "passage_id IS NULL AND assignment_id IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_practice_session_unique_null_passage_legacy",
        table_name="practice_session",
    )
    op.drop_index(
        "ix_practice_session_unique_null_passage", table_name="practice_session"
    )
    op.drop_index("ix_practice_session_unique_legacy_passage", table_name="practice_session")
    op.drop_index("ix_practice_session_unique", table_name="practice_session")
    op.create_index(
        "ix_practice_session_unique",
        "practice_session",
        ["student_id", "session_date", "passage_id", "mode"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NOT NULL"),
    )
    op.create_index(
        "ix_practice_session_unique_null_passage",
        "practice_session",
        ["student_id", "session_date", "mode"],
        unique=True,
        postgresql_where=sa.text("passage_id IS NULL"),
    )
    op.drop_column("attempt", "item_snapshot")
    op.drop_constraint(
        "fk_practice_session_assignment", "practice_session", type_="foreignkey"
    )
    op.drop_index("ix_practice_session_assignment_id", table_name="practice_session")
    op.drop_column("practice_session", "assignment_id")
    op.drop_constraint("fk_classroom_current_exercise", "classroom", type_="foreignkey")
    op.drop_index("ix_classroom_current_exercise_id", table_name="classroom")
    op.drop_column("classroom", "current_exercise_id")
    op.drop_index("ix_classroom_exercise_status", table_name="classroom_exercise")
    op.drop_index(
        "ix_classroom_exercise_classroom_id", table_name="classroom_exercise"
    )
    op.drop_table("classroom_exercise")
