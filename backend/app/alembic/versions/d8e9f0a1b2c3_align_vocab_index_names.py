"""align vocabulary governance/leaderboard index names with models (#517)

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a2b3
Create Date: 2026-11-25

迁移里单列索引用了 ``ix_vocab_*`` 短前缀，而 SQLModel ``Field(index=True)``
默认生成 ``ix_<table>_<column>``（``ix_vocabulary_*``）。autogenerate 会因此
把索引视为“删旧建新”，CI 的迁移-模型一致性校验失败。此处只做重命名，并
补上两张新表遗漏的 ``tenant_id`` 单列索引（复合索引已存在）。
"""

from alembic import op

revision = "d8e9f0a1b2c3"
down_revision = "c7d8e9f0a2b3"
branch_labels = None
depends_on = None

RENAMES = (
    # 词库版本快照
    ("ix_vocab_book_version_action", "ix_vocabulary_book_version_action"),
    ("ix_vocab_book_version_book_id", "ix_vocabulary_book_version_book_id"),
    ("ix_vocab_book_version_content_hash", "ix_vocabulary_book_version_content_hash"),
    # 授权审计
    ("ix_vocab_license_audit_actor_id", "ix_vocabulary_license_audit_actor_id"),
    ("ix_vocab_license_audit_book_id", "ix_vocabulary_license_audit_book_id"),
    ("ix_vocab_license_audit_target_type", "ix_vocabulary_license_audit_target_type"),
    ("ix_vocab_license_audit_word_id", "ix_vocabulary_license_audit_word_id"),
    # 班内榜设置
    ("ix_vocab_leaderboard_setting_classroom_id", "ix_vocabulary_leaderboard_setting_classroom_id"),
    ("ix_vocab_leaderboard_setting_tenant_id", "ix_vocabulary_leaderboard_setting_tenant_id"),
    ("ix_vocab_leaderboard_setting_updated_by", "ix_vocabulary_leaderboard_setting_updated_by"),
    # 班内榜参与档案
    ("ix_vocab_leaderboard_participant_classroom_id", "ix_vocabulary_leaderboard_participant_classroom_id"),
    ("ix_vocab_leaderboard_participant_student_id", "ix_vocabulary_leaderboard_participant_student_id"),
    ("ix_vocab_leaderboard_participant_tenant_id", "ix_vocabulary_leaderboard_participant_tenant_id"),
)

NEW_TENANT_INDEXES = (
    ("ix_vocabulary_book_version_tenant_id", "vocabulary_book_version"),
    ("ix_vocabulary_license_audit_tenant_id", "vocabulary_license_audit"),
)


def upgrade() -> None:
    for old, new in RENAMES:
        op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')
    for name, table in NEW_TENANT_INDEXES:
        op.create_index(name, table, ["tenant_id"], unique=False)


def downgrade() -> None:
    for name, table in NEW_TENANT_INDEXES:
        op.drop_index(name, table_name=table)
    for old, new in RENAMES:
        op.execute(f'ALTER INDEX "{new}" RENAME TO "{old}"')
