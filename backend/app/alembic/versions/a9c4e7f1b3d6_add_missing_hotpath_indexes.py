"""add missing hot-path indexes

Revision ID: a9c4e7f1b3d6
Revises: b8f3e4a0c6d2
Create Date: 2026-09-30 13:00:00.000000

补齐查询热路径缺失的索引（2026-09-30 性能审计）：
- repeat_sentence.passage_id：/today、/board、发布快照、篇目列表都按篇目查句子
- scenario_question.scenario_id：抽题按主题查问题（学生端每次刷新）
- practice_session.classroom_id：board/发布历史按课堂拉会话
- practice_session.student_id：trail/结算直查学生会话（原只有 student_id
  开头的部分唯一索引，WHERE 条件不覆盖这些场景）
- classroom.owner_id：教师工作台课堂列表
- passage.unit_id：路径/指派/单元篇目计数
- attempt (status, created_at)：board 引擎探测 order by created_at desc
"""
import sqlalchemy as sa
from alembic import op

revision = "a9c4e7f1b3d6"
down_revision = "b8f3e4a0c6d2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        op.f("ix_repeat_sentence_passage_id"), "repeat_sentence", ["passage_id"]
    )
    op.create_index(
        op.f("ix_scenario_question_scenario_id"), "scenario_question", ["scenario_id"]
    )
    op.create_index(
        op.f("ix_practice_session_classroom_id"), "practice_session", ["classroom_id"]
    )
    op.create_index(
        op.f("ix_practice_session_student_id"), "practice_session", ["student_id"]
    )
    op.create_index(op.f("ix_classroom_owner_id"), "classroom", ["owner_id"])
    op.create_index(op.f("ix_passage_unit_id"), "passage", ["unit_id"])
    op.create_index(
        "ix_attempt_status_created_at", "attempt", ["status", sa.text("created_at")]
    )


def downgrade():
    op.drop_index("ix_attempt_status_created_at", table_name="attempt")
    op.drop_index(op.f("ix_passage_unit_id"), table_name="passage")
    op.drop_index(op.f("ix_classroom_owner_id"), table_name="classroom")
    op.drop_index(op.f("ix_practice_session_student_id"), table_name="practice_session")
    op.drop_index(op.f("ix_practice_session_classroom_id"), table_name="practice_session")
    op.drop_index(op.f("ix_scenario_question_scenario_id"), table_name="scenario_question")
    op.drop_index(op.f("ix_repeat_sentence_passage_id"), table_name="repeat_sentence")
