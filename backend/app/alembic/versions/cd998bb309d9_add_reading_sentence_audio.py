"""add reading_sentence_audio

Revision ID: cd998bb309d9
Revises: f2b8c4e91a37
Create Date: 2026-10-28 17:19:16.864192

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cd998bb309d9'
down_revision = 'f2b8c4e91a37'
branch_labels = None
depends_on = None


def upgrade():
    # 本机库 admin_metrics_daily.updated_at 的 NOT NULL 漂移不迁就（项目规约）
    op.add_column('passage', sa.Column('reading_sentence_audio', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('passage', 'reading_sentence_audio')
