"""add export_job and export_audit for original-audio ZIP

Revision ID: e8a1c4b90d27
Revises: 1f4592d70e43
Create Date: 2026-10-27 14:40:00.000000

口语原音频 ZIP（P0）：ExportJob 是数据库队列，ExportAudit 记录
谁在何时以什么范围导出 / 下载 / 失败 / 过期。不回填历史作答。
"""

import sqlalchemy as sa
from alembic import op

revision = "e8a1c4b90d27"
down_revision = "1f4592d70e43"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "export_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("filter_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("artifact_relpath", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("included_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("download_name", sa.String(length=255), nullable=True),
        sa.Column(
            "confirm_contains_student_audio",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["requester_user_id"], ["user.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_export_job_requester_user_id", "export_job", ["requester_user_id"]
    )
    op.create_index("ix_export_job_scope", "export_job", ["scope"])
    op.create_index("ix_export_job_status", "export_job", ["status"])
    op.create_index(
        "ix_export_job_requester_created",
        "export_job",
        ["requester_user_id", "created_at"],
    )
    op.create_index(
        "ix_export_job_status_expires", "export_job", ["status", "expires_at"]
    )
    op.create_table(
        "export_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["export_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_audit_job_id", "export_audit", ["job_id"])
    op.create_index(
        "ix_export_audit_actor_user_id", "export_audit", ["actor_user_id"]
    )
    op.create_index("ix_export_audit_action", "export_audit", ["action"])


def downgrade():
    op.drop_index("ix_export_audit_action", table_name="export_audit")
    op.drop_index("ix_export_audit_actor_user_id", table_name="export_audit")
    op.drop_index("ix_export_audit_job_id", table_name="export_audit")
    op.drop_table("export_audit")
    op.drop_index("ix_export_job_status_expires", table_name="export_job")
    op.drop_index("ix_export_job_requester_created", table_name="export_job")
    op.drop_index("ix_export_job_status", table_name="export_job")
    op.drop_index("ix_export_job_scope", table_name="export_job")
    op.drop_index("ix_export_job_requester_user_id", table_name="export_job")
    op.drop_table("export_job")
