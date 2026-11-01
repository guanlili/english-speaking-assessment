"""multi-tenant c1 business tenant columns

Revision ID: c4e8a1f7b2d3
Revises: a7c4d92e1f83
Create Date: 2026-11-01 00:20:00

多租户 C1：全业务表租户归属落列。

B1 锚点定式推广到全部 30 张业务表（B 类 18 + C 类归校 3 + D 类 8 +
清单补漏 VocabularyBookItem）：tenant_id NOT NULL + 列级 server_default
固定默认租户 UUID——存量自动归位（单校窗口唯一真值），增量漏写不可能。
索引先统一单列（RLS 收口时按真实查询改复合前缀，设计稿 §4.3「不给
所有列机械加索引」的例外在此显式声明取舍）；FK 全命名（匿名 FK 的
downgrade drop_constraint(None) 会坏——B1 教训）。

不动：tenant/platform_operator（身份层）、admin_metrics_daily/
admin_cost_reconcile/changelog_entry（平台口径表，设计稿 §4.2）。

C1 是纯数据地基：零查询行为变化（查询侧租户过滤随 C3 RLS 激活）。
设计依据 docs/multi-tenant-design.md §4.2/§9-2、
docs/multi-tenant-a-inventory.md §1.1/§2-1。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c4e8a1f7b2d3'
down_revision = 'a7c4d92e1f83'
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# B 类（教学业务）+ C 类归校（unit/sentence_frame/vocab_level_entry，
# V1.0 FR-04：存量归原校、授权后入平台目录）+ D 类全量
_TABLES = [
    # 题库
    "unit",
    "passage",
    "repeat_sentence",
    "scenario",
    "scenario_question",
    "instruction",
    "sentence_frame",
    # 课堂与教学
    "classroom_exercise",
    "composer_draft",
    "practice_session",
    "item_listen",
    "instruction_ack",
    "student_badge",
    "student_expression_favorite",
    "student_frame_favorite",
    "classroom_review",
    "followup_batch",
    "classroom_message",
    # 背单词
    "vocabulary_word",
    "vocabulary_book",
    "vocabulary_book_item",
    "vocabulary_assignment",
    "vocabulary_assignment_target",
    "vocabulary_session",
    "vocabulary_answer",
    "vocabulary_ai_cache",
    "vocab_level_entry",
    # 作答与导出
    "attempt",
    "export_job",
    "export_audit",
]


def upgrade():
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                'tenant_id',
                sa.Uuid(),
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
                nullable=False,
            ),
        )
        op.create_index(
            op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False
        )
        op.create_foreign_key(
            f'fk_{table}_tenant', table, 'tenant', ['tenant_id'], ['id']
        )


def downgrade():
    for table in reversed(_TABLES):
        op.drop_constraint(f'fk_{table}_tenant', table, type_='foreignkey')
        op.drop_index(op.f(f'ix_{table}_tenant_id'), table=table)
        op.drop_column(table, 'tenant_id')
