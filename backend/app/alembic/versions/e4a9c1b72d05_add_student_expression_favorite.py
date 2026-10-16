"""add student expression favorites

升级表达收藏跟课堂档案走，换设备或清掉浏览器缓存后仍在。
"""

import sqlalchemy as sa
from alembic import op

revision = "e4a9c1b72d05"
down_revision = "b22ce1e19087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_expression_favorite",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "text", name="uq_student_expression_text"),
    )
    op.create_index(
        op.f("ix_student_expression_favorite_student_id"),
        "student_expression_favorite",
        ["student_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_student_expression_favorite_student_id"),
        table_name="student_expression_favorite",
    )
    op.drop_table("student_expression_favorite")
