"""three question types independent: standalone sentences, item-based assignment

Revision ID: a8e41d2c7f10
Revises: f3a2c81b9d04
Create Date: 2026-09-29 02:30:00.000000

产品决策（2026-09-29）：题目库三种题型互相独立。
- repeat_sentence.passage_id 放开为可空：复述句可独立创建与指派（挂篇目仍用于自主练习）
- classroom.assigned_items：按题指派存 JSON 集合（passage/repeat/question），非空时优先于单元指派
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a8e41d2c7f10'
down_revision = 'f3a2c81b9d04'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "repeat_sentence", "passage_id", existing_type=sa.UUID(), nullable=True
    )
    op.add_column(
        "classroom",
        sa.Column("assigned_items", sa.JSON(), nullable=True),
    )
    op.add_column(
        "repeat_sentence",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("repeat_sentence", "created_at")
    op.drop_column("classroom", "assigned_items")
    op.execute(
        "DELETE FROM repeat_sentence WHERE passage_id IS NULL"
    )
    op.alter_column(
        "repeat_sentence", "passage_id", existing_type=sa.UUID(), nullable=False
    )
