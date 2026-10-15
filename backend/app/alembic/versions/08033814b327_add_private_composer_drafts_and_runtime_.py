"""add private composer drafts and runtime issue reports

Revision ID: 08033814b327
Revises: c100e2d8ff20
Create Date: 2026-10-16 07:36:57.885255

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '08033814b327'
down_revision = 'c100e2d8ff20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("composer_draft",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["classroom_id"], ["classroom.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("classroom_id", "owner_id", name="uq_composer_draft_owner"),
    )
    op.create_index("ix_composer_draft_classroom_id", "composer_draft", ["classroom_id"])
    op.create_index("ix_composer_draft_owner_id", "composer_draft", ["owner_id"])
    op.add_column("practice_session", sa.Column("runtime_issue", sa.String(32), nullable=True))
    op.add_column("practice_session", sa.Column("runtime_issue_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("practice_session", "runtime_issue_at")
    op.drop_column("practice_session", "runtime_issue")
    op.drop_table("composer_draft")
