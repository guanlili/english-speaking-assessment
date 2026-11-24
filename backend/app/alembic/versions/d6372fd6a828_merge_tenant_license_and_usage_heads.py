"""merge tenant license and usage heads

Revision ID: d6372fd6a828
Revises: b2c3d4e5f6a7, c3d4e5f6a7b8
Create Date: 2026-11-24 04:50:30.104589

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'd6372fd6a828'
down_revision = ('b2c3d4e5f6a7', 'c3d4e5f6a7b8')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
