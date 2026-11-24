"""align pre-existing vocabulary index names with models

CI 的迁移-模型一致性校验发现 master 上已有漂移：

- ``vocab_placement_result``：迁移里建的是 ``ix_vocab_placement_result_band``，
  模型 ``Field(index=True)`` 自动生成 ``ix_vocab_placement_result_recommended_band``；
- ``vocabulary_content_review_audit``：迁移里是 ``ix_vocab_review_audit_*``，
  模型自动生成 ``ix_vocabulary_content_review_audit_*``。

本迁移只重命名索引，不改变列、约束或数据；upgrade 后数据库与模型同名。

Revision ID: e5f6a7b8c9d0
Revises: d6372fd6a828
Create Date: 2026-11-24
"""

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d6372fd6a828"
branch_labels = None
depends_on = None

RENAMES = (
    (
        "ix_vocab_placement_result_band",
        "ix_vocab_placement_result_recommended_band",
    ),
    (
        "ix_vocab_review_audit_tenant_id",
        "ix_vocabulary_content_review_audit_tenant_id",
    ),
    (
        "ix_vocab_review_audit_word_id",
        "ix_vocabulary_content_review_audit_word_id",
    ),
    (
        "ix_vocab_review_audit_actor_id",
        "ix_vocabulary_content_review_audit_actor_id",
    ),
    (
        "ix_vocab_review_audit_action",
        "ix_vocabulary_content_review_audit_action",
    ),
)


def upgrade() -> None:
    for old, new in RENAMES:
        op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')


def downgrade() -> None:
    for old, new in reversed(RENAMES):
        op.execute(f'ALTER INDEX "{new}" RENAME TO "{old}"')
