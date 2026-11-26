"""scope PK answer idempotency key to player

Revision ID: d4e5f6a7b8c9
Revises: f3a4b5c6d7e8
Create Date: 2026-11-26 15:10:00.000000

D12：PK 作答幂等键按玩家维度唯一。旧约束把 ``idempotency_key`` 建成全局唯一，
同局两名玩家同题同 attempt 生成相同键时，后到者被唯一约束/重放查询误判为冲突
（422）。改为 ``(player_id, idempotency_key)``：两玩家可各自提交同题同键，
同玩家重复同键仍走幂等重放。

- upgrade：删除全局唯一约束，建玩家维度复合唯一约束；
- downgrade：还原全局唯一约束。旧约束在生产已保证非空键全局不重复，回滚不会
  撞重复行；若回滚前出现跨玩家同键数据，重建全局约束可能失败，需先人工清理。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None

TABLE = "vocab_pk_answer"
CONSTRAINT = "uq_vocab_pk_answer_idempotency"


def upgrade():
    op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
    op.create_unique_constraint(
        CONSTRAINT,
        TABLE,
        ["player_id", "idempotency_key"],
    )


def downgrade():
    op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
    op.create_unique_constraint(CONSTRAINT, TABLE, ["idempotency_key"])
