"""add per sentence reading durations

Revision ID: c100e2d8ff20
Revises: dc44acace33b
Create Date: 2026-10-12 19:53:43.308742

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c100e2d8ff20"
down_revision = "dc44acace33b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "passage", sa.Column("reading_sentence_seconds", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column("passage", "reading_sentence_seconds")
