"""add unit.scenario_id (unit → scenario binding)

Revision ID: e5b711a3c9d2
Revises: d4e5f6a7b8c9
Create Date: 2026-11-28 18:00:00.000000

#611：单元一键指派 / 今日计划取情景问答时，原先只按 ``unit.topic == scenario.topic``
精确字符串匹配。王府实际数据里单元 topic 是 ``Design``/``Mock Test``/``Practice``，
情景 topic 是 ``Pets``/``School Life``/``CULTURE``…，交集为 0，于是问答位被静默跳过。

改为单元显式绑定情景：``unit.scenario_id`` 可空 FK → ``scenario.id`` ON DELETE SET
NULL。绑定后问答取题以绑定为准，未绑定时仍退回 topic 匹配（向后兼容）。

- additive：只加可空列 + 索引 + 外键，不改存量数据、不回填；
- downgrade 可逆，删列即连带删索引与外键。
"""

import sqlalchemy as sa
from alembic import op

revision = "e5b711a3c9d2"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None

TABLE = "unit"
COLUMN = "scenario_id"


def upgrade():
    op.add_column(TABLE, sa.Column(COLUMN, sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_unit_scenario_id"), TABLE, [COLUMN], unique=False)
    op.create_foreign_key(
        "fk_unit_scenario_id_scenario",
        TABLE,
        "scenario",
        [COLUMN],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_unit_scenario_id_scenario", TABLE, type_="foreignkey")
    op.drop_index(op.f("ix_unit_scenario_id"), table_name=TABLE)
    op.drop_column(TABLE, COLUMN)
