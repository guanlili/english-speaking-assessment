"""multi-tenant c4a rls policies

Revision ID: b5d9e4f1a8c7
Revises: d8f3b2e6c4a9
Create Date: 2026-11-01 03:40:00

多租户 C4a：全业务表 RLS 策略落地（激活前置）。

- 32 张业务表（C1 的 30 张 + 锚点 classroom/student）：
  ENABLE + FORCE ROW LEVEL SECURITY + 策略 tenant_isolation：
  USING / WITH CHECK (
    coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text
  )——缺上下文（NULL/''）永不匹配即默认拒绝（A 期原型 P1 验证）。
- 不启 RLS：tenant / user / platformoperator（身份层——登录与账号管理
  天然跨租户，由应用层校验租户归属）；admin_metrics_daily /
  admin_cost_reconcile / changelog_entry（平台口径表）。
- FORCE 对表 owner 同样生效；superuser 始终豁免——C4a 形态下应用仍用
  owner 连接（行为与 C3 等价），C4b 切换受限角色（esa_app NOBYPASSRLS /
  esa_platform BYPASSRLS）后策略真正生效。
- 应用侧配套（同 PR）：平台路由/后台任务已切 PlatformSessionDep /
  platform_engine（跨租户口径通道）；学校流量经 C3 中间件携带 tid 上下文。

downgrade 可整体摘除策略（多校数据混入后回滚会失去隔离——见设计稿 §9-5）。
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b5d9e4f1a8c7'
down_revision = 'd8f3b2e6c4a9'
branch_labels = None
depends_on = None

# 32 张业务表 = C1 的 30 张 + classroom/student（user 不在此列）
RLS_TABLES = [
    # 题库
    "unit",
    "passage",
    "repeat_sentence",
    "scenario",
    "scenario_question",
    "instruction",
    "sentence_frame",
    # 课堂与教学
    "classroom",
    "classroom_exercise",
    "composer_draft",
    "practice_session",
    "item_listen",
    "instruction_ack",
    "student",
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

POLICY = (
    "coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text"
)


def upgrade():
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({POLICY}) WITH CHECK ({POLICY})"
        )


def downgrade():
    for table in reversed(RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
