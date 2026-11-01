"""multi-tenant c2 composite unique

Revision ID: d8f3b2e6c4a9
Revises: c4e8a1f7b2d3
Create Date: 2026-11-01 02:10:00

多租户 C2：唯一性从全局收窄到校内（两校可同名），A 期清单 §2-1/§2-2：

1. passage.slug：唯一索引 ix_passage_slug（全局）→ 非唯一索引 +
   复合唯一约束 uq_passage_tenant_slug (tenant_id, slug)
2. scenario.topic：同形态 → uq_scenario_tenant_topic (tenant_id, topic)
3. item_listen：uq_item_listen_scope 列集扩为
   (tenant_id, student_id, session_id, item_id)——class_runtime.py 的
   原生 UPSERT 按该约束名引用，代码同 PR 同步（插入列含 tenant_id）
4. 幂等键（attempt/vocabulary_answer）保持全局唯一（设计稿 §4.3），
   命中跨租户按不存在处理（代码层核验，本迁移不动键结构）

单校窗口内复合约束与原全局唯一等价（全部行同租户），存量无冲突；
downgrade 在多校写入后不可回滚（跨校同名会撞回全局唯一）。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd8f3b2e6c4a9'
down_revision = 'c4e8a1f7b2d3'
branch_labels = None
depends_on = None


def upgrade():
    # passage.slug：全局唯一索引 → 非唯一 + 校内复合唯一约束
    op.drop_index('ix_passage_slug', table_name='passage')
    op.create_index('ix_passage_slug', 'passage', ['slug'], unique=False)
    op.create_unique_constraint(
        'uq_passage_tenant_slug', 'passage', ['tenant_id', 'slug']
    )
    # scenario.topic：同形态
    op.drop_index('ix_scenario_topic', table_name='scenario')
    op.create_index('ix_scenario_topic', 'scenario', ['topic'], unique=False)
    op.create_unique_constraint(
        'uq_scenario_tenant_topic', 'scenario', ['tenant_id', 'topic']
    )
    # item_listen：约束列集扩租户前缀（同名重建）
    op.drop_constraint('uq_item_listen_scope', 'item_listen', type_='unique')
    op.create_unique_constraint(
        'uq_item_listen_scope',
        'item_listen',
        ['tenant_id', 'student_id', 'session_id', 'item_id'],
    )


def downgrade():
    # 前提：未发生跨校写入（两校同 slug/topic/作用域行会撞回全局唯一）
    op.drop_constraint('uq_item_listen_scope', 'item_listen', type_='unique')
    op.create_unique_constraint(
        'uq_item_listen_scope',
        'item_listen',
        ['student_id', 'session_id', 'item_id'],
    )
    op.drop_constraint('uq_scenario_tenant_topic', 'scenario', type_='unique')
    op.drop_index('ix_scenario_topic', table_name='scenario')
    op.create_index('ix_scenario_topic', 'scenario', ['topic'], unique=True)
    op.drop_constraint('uq_passage_tenant_slug', 'passage', type_='unique')
    op.drop_index('ix_passage_slug', table_name='passage')
    op.create_index('ix_passage_slug', 'passage', ['slug'], unique=True)
