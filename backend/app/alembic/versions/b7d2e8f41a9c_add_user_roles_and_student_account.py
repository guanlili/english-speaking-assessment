"""add user roles and student account

Revision ID: b7d2e8f41a9c
Revises: 14046ec75466
Create Date: 2026-09-28 12:00:00.000000

统一用户体系：User 加 role/username/must_change_password（email 改可空，
学生用学号登录），Student 加 user_id 关联账号并回填存量角色。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b7d2e8f41a9c"
down_revision = "14046ec75466"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) user：email 可空（学生无邮箱），新增角色/学号/初始密码标记
    op.alter_column("user", "email", existing_type=sa.String(255), nullable=True)
    op.add_column(
        "user",
        sa.Column("role", sa.String(16), nullable=False, server_default="teacher"),
    )
    op.add_column("user", sa.Column("username", sa.String(64), nullable=True))
    op.add_column(
        "user",
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    # 存量回填：管理员 → admin，其余（教师用途）→ teacher
    op.execute(
        "UPDATE \"user\" SET role = CASE WHEN is_superuser THEN 'admin' ELSE 'teacher' END"
    )
    op.create_index("ix_user_role", "user", ["role"])
    op.create_index("ix_user_username", "user", ["username"], unique=True)

    # 2) student：关联登录账号；一个账号一间课堂一份档案
    op.add_column(
        "student",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_student_user_classroom_unique",
        "student",
        ["user_id", "classroom_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_student_user_classroom_unique", table_name="student")
    op.drop_column("student", "user_id")
    op.drop_index("ix_user_username", table_name="user")
    op.drop_index("ix_user_role", table_name="user")
    op.drop_column("user", "must_change_password")
    op.drop_column("user", "username")
    op.drop_column("user", "role")
    op.alter_column("user", "email", existing_type=sa.String(255), nullable=False)
