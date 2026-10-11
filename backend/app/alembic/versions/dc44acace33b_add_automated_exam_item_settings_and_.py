"""add automated exam item settings and session phases

Revision ID: dc44acace33b
Revises: a3f1d90c2b47
Create Date: 2026-10-11 12:18:25.259555

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "dc44acace33b"
down_revision = "a3f1d90c2b47"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("passage", "repeat_sentence", "scenario_question", "instruction"):
        op.add_column(table, sa.Column("exam_settings", sa.JSON(), nullable=True))
    op.add_column(
        "practice_session", sa.Column("exam_flow_state", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column("practice_session", "exam_flow_state")
    for table in ("instruction", "scenario_question", "repeat_sentence", "passage"):
        op.drop_column(table, "exam_settings")
