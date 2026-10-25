"""add admin_cost_reconcile

Revision ID: 988c9d601a00
Revises: 2abc063ad612
Create Date: 2026-10-25

费用对账表：管理员手工录入当月实际账单金额。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "988c9d601a00"
down_revision = "2abc063ad612"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_cost_reconcile",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("amount_cny", sa.Float(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("month"),
    )


def downgrade() -> None:
    op.drop_table("admin_cost_reconcile")
