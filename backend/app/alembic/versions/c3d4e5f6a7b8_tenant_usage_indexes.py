"""add tenant-time composite indexes for per-tenant daily usage aggregation

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-11-24 16:00:00.000000

#517 B 部分：按租户按天用量聚合（``admin/tenants/{id}/usage``）。所有查询都是
``tenant_id = :t AND time_col >= :start AND time_col < :end`` 形态；既有索引只有
单列 ``tenant_id``，补 ``(tenant_id, 时间列)`` 复合索引覆盖范围裁剪。

- additive：只加索引，不改表结构、不回填、不新建事件管道。
- 索引同时声明在对应模型 ``__table_args__``，避免模型 / 迁移漂移。
- downgrade 可逆：按名 drop_index。
"""

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


# (表名, 索引名, 时间列)
INDEXES = [
    ("vocabulary_answer", "ix_vocabulary_answer_tenant_answered_at", "answered_at"),
    (
        "vocabulary_assignment",
        "ix_vocabulary_assignment_tenant_published_at",
        "published_at",
    ),
    ("vocabulary_session", "ix_vocabulary_session_tenant_submitted_at", "submitted_at"),
    ("vocab_pk_match", "ix_vocab_pk_match_tenant_started_at", "started_at"),
    (
        "vocab_placement_result",
        "ix_vocab_placement_result_tenant_submitted_at",
        "submitted_at",
    ),
    ("export_audit", "ix_export_audit_tenant_created_at", "created_at"),
    (
        "vocabulary_content_review_audit",
        "ix_vocab_review_audit_tenant_created_at",
        "created_at",
    ),
    (
        "classroom_exercise",
        "ix_classroom_exercise_tenant_published_at",
        "published_at",
    ),
    (
        "vocab_farm_plot",
        "ix_vocab_farm_plot_tenant_last_harvested_at",
        "last_harvested_at",
    ),
]


def upgrade():
    for table, index_name, time_col in INDEXES:
        op.create_index(index_name, table, ["tenant_id", time_col], unique=False)


def downgrade():
    for table, index_name, _time_col in reversed(INDEXES):
        op.drop_index(index_name, table_name=table)
