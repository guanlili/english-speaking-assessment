"""add question bank owner

题库四类题目记录创建者：只有创建者和管理员能改/删；存量行 owner_id 为空，
所有教师仍可编辑（行为不变）。

Revision ID: a7d3e9f1c205
Revises: f1c8a4e27b90
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d3e9f1c205"
down_revision = "f1c8a4e27b90"
branch_labels = None
depends_on = None

TABLES = ("passage", "repeat_sentence", "scenario_question", "instruction")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("owner_id", sa.Uuid(), nullable=True))
        op.create_index(f"ix_{table}_owner_id", table, ["owner_id"])
        op.create_foreign_key(
            f"fk_{table}_owner_id",
            table,
            "user",
            ["owner_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_constraint(f"fk_{table}_owner_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_owner_id", table_name=table)
        op.drop_column(table, "owner_id")
