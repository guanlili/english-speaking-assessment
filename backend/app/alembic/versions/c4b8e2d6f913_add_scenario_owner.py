"""add scenario owner

情景主题记录创建者：改名/启停归创建者；存量主题 owner_id 为空，
沿用「组内题目都可改才能管理」（行为不变）。

Revision ID: c4b8e2d6f913
Revises: a7d3e9f1c205
"""

import sqlalchemy as sa
from alembic import op

revision = "c4b8e2d6f913"
down_revision = "a7d3e9f1c205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenario", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_index("ix_scenario_owner_id", "scenario", ["owner_id"])
    op.create_foreign_key(
        "fk_scenario_owner_id",
        "scenario",
        "user",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scenario_owner_id", "scenario", type_="foreignkey")
    op.drop_index("ix_scenario_owner_id", table_name="scenario")
    op.drop_column("scenario", "owner_id")
