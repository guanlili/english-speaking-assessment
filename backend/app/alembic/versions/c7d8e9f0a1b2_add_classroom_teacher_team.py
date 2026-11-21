"""add classroom teacher team

Revision ID: c7d8e9f0a1b2
Revises: ffe40ee66257
Create Date: 2026-11-21 17:20:00

课堂教师团队：`classroom_teacher` membership 是授权唯一事实源，
`classroom.owner_id` 保留为主教师展示/转让依据。迁移把存量 owner
回填成 owner membership，并开启同款 tenant RLS。
"""

from alembic import op

import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "ffe40ee66257"
branch_labels = None
depends_on = None


RLS_POLICY = (
    "coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text"
)


def upgrade():
    op.create_table(
        "classroom_teacher",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("classroom_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            server_default=sa.text("'00000000-0000-0000-0000-000000000001'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["classroom_id"], ["classroom.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "classroom_id", "user_id", name="uq_classroom_teacher_member"
        ),
    )
    op.create_index(
        op.f("ix_classroom_teacher_classroom_id"),
        "classroom_teacher",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_classroom_teacher_user_id"),
        "classroom_teacher",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_classroom_teacher_tenant_id"),
        "classroom_teacher",
        ["tenant_id"],
        unique=False,
    )
    # 存量 owner 全部回填 owner membership；owner_id 为空的无主课堂由
    # school_admin 绑定 owner 时走 API 同步逻辑补 membership。
    op.execute(
        """
        INSERT INTO classroom_teacher
            (id, classroom_id, user_id, role, tenant_id, created_by, created_at)
        SELECT
            gen_random_uuid(), c.id, c.owner_id, 'owner',
            c.tenant_id, c.owner_id, COALESCE(c.created_at, now())
        FROM classroom c
        WHERE c.owner_id IS NOT NULL
        ON CONFLICT (classroom_id, user_id) DO NOTHING
        """
    )
    op.execute("ALTER TABLE classroom_teacher ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE classroom_teacher FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON classroom_teacher "
        f"USING ({RLS_POLICY}) WITH CHECK ({RLS_POLICY})"
    )


def downgrade():
    op.drop_table("classroom_teacher")
