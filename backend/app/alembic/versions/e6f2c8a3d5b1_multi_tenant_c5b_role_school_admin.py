"""multi-tenant c5b role school_admin

Revision ID: e6f2c8a3d5b1
Revises: b5d9e4f1a8c7
Create Date: 2026-11-02 00:30:00

多租户 C5b：校级管理员角色值改名 admin → school_admin（设计稿 §3.2
「旧学校 admin 迁为 school_admin」的最终落地）。

- 存量 UPDATE role='admin' → 'school_admin'（生产 3 个账号）
- 前端旧会话兼容：esa:role 缓存与 JWT role 声明为 'admin' 的浏览器
  在重登前由前端双值兼容兜底（过渡一个版本）
- downgrade 镜像还原
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e6f2c8a3d5b1'
down_revision = 'b5d9e4f1a8c7'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE \"user\" SET role = 'school_admin' WHERE role = 'admin'")


def downgrade():
    op.execute("UPDATE \"user\" SET role = 'admin' WHERE role = 'school_admin'")
