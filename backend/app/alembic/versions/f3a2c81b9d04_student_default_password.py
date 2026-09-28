"""student accounts: uniform default password, no forced change

Revision ID: f3a2c81b9d04
Revises: d94c1a7f03b5
Create Date: 2026-09-28 17:20:00.000000

产品决策（2026-09-28）：学生账号统一默认密码 brs123456，登录后不强制改密。
存量学生账号（含已自改密码的）一次性重置为默认密码并清除改密标记；
教师仍可在名单里单个/批量重置，学生可自行修改。
"""
from alembic import op
from sqlalchemy import text

from app.core.security import DEFAULT_STUDENT_PASSWORD, get_password_hash

# revision identifiers, used by Alembic.
revision = 'f3a2c81b9d04'
down_revision = 'd94c1a7f03b5'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(
        text(
            'UPDATE "user" SET hashed_password = :hp, '
            "must_change_password = false WHERE role = 'student'"
        ),
        {"hp": get_password_hash(DEFAULT_STUDENT_PASSWORD)},
    )


def downgrade():
    # 无法还原各学生原密码；此迁移不可实质回退，仅保持链路完整
    pass
