"""add changelog_entry

Revision ID: 1f4592d70e43
Revises: de1539d6dd4c
Create Date: 2026-10-26

平台更新日志表：管理员发布、教师与管理员可见（学生端不开放）。
注：autogenerate 同时探测到本机开发库 admin_metrics_daily.updated_at 为
NOT NULL（迁移链与模型均 nullable），属本机库局部漂移，不迁就、已剔除。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = '1f4592d70e43'
down_revision = 'de1539d6dd4c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('changelog_entry',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
    sa.Column('title_zh', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('title_en', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
    sa.Column('body_zh', sa.Text(), nullable=True),
    sa.Column('body_en', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_changelog_entry_day'), 'changelog_entry', ['day'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_changelog_entry_day'), table_name='changelog_entry')
    op.drop_table('changelog_entry')
