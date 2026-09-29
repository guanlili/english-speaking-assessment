"""add classroom teaching metadata

Revision ID: 7a1b2c3d4e5f
Revises: 6f0d8c1a2b3c
"""

from alembic import op
import sqlalchemy as sa


revision = "7a1b2c3d4e5f"
down_revision = "6f0d8c1a2b3c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classroom",
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
            server_default="未命名课堂",
        ),
    )
    op.add_column("classroom", sa.Column("grade", sa.String(length=64), nullable=True))
    op.add_column(
        "classroom",
        sa.Column("teaching_goal", sa.String(length=255), nullable=True),
    )
    op.alter_column("classroom", "name", server_default=None)


def downgrade() -> None:
    op.drop_column("classroom", "teaching_goal")
    op.drop_column("classroom", "grade")
    op.drop_column("classroom", "name")
