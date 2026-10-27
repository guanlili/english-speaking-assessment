"""add export_job.kind and classroom.show_report_percentile

Revision ID: f2b8c4e91a37
Revises: e8a1c4b90d27
Create Date: 2026-10-27 18:10:00.000000

学生个人学情 PDF（P1）：ExportJob.kind 区分录音 ZIP 与学情 PDF，
旧行回填 audio_zip。课堂级开关默认显示班级位置。不回填、不重算历史作答。
"""

import sqlalchemy as sa
from alembic import op

revision = "f2b8c4e91a37"
down_revision = "e8a1c4b90d27"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "export_job",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="audio_zip",
        ),
    )
    op.create_index("ix_export_job_kind", "export_job", ["kind"])
    op.add_column(
        "classroom",
        sa.Column(
            "show_report_percentile",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade():
    op.drop_column("classroom", "show_report_percentile")
    op.drop_index("ix_export_job_kind", table_name="export_job")
    op.drop_column("export_job", "kind")
