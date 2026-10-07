"""add practice_session.tab_switch_seconds (exam away duration)

Revision ID: f7a3c9e25b41
Revises: e2c8b7a4d9f1
Create Date: 2026-10-07 10:00:00.000000

模考防切屏时长（2026-10-07）：
- practice_session.tab_switch_seconds：切回（visible 相位）时上报的累计
  离屏秒数，与 tab_switch_count 配套——次数之外老师还能看到离开了多久；
- 开考同步改为确认页显式触发（POST /exam/start），不加列、只改流程。
"""

import sqlalchemy as sa
from alembic import op

revision = "f7a3c9e25b41"
down_revision = "e2c8b7a4d9f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "practice_session",
        sa.Column(
            "tab_switch_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade():
    op.drop_column("practice_session", "tab_switch_seconds")
