"""add classroom homework exercise

课后作业与课上当前发布分开保存，再发布课堂练习不会顶掉作业。
"""

import sqlalchemy as sa
from alembic import op

revision = "f1c8a4e27b90"
down_revision = "e4a9c1b72d05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classroom",
        sa.Column("homework_exercise_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_classroom_homework_exercise_id",
        "classroom",
        ["homework_exercise_id"],
    )
    op.create_foreign_key(
        "fk_classroom_homework_exercise_id",
        "classroom",
        "classroom_exercise",
        ["homework_exercise_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_classroom_homework_exercise_id", "classroom", type_="foreignkey"
    )
    op.drop_index("ix_classroom_homework_exercise_id", table_name="classroom")
    op.drop_column("classroom", "homework_exercise_id")
