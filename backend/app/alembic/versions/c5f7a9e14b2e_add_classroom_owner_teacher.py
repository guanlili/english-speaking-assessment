"""add classroom owner teacher

Revision ID: c5f7a9e14b2e
Revises: b4e6d9f32c8a
Create Date: 2026-09-27 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c5f7a9e14b2e"
down_revision = "b4e6d9f32c8a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classroom",
        sa.Column("owner_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_classroom_owner_user",
        "classroom",
        "user",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_classroom_owner_user", "classroom", type_="foreignkey")
    op.drop_column("classroom", "owner_id")
