"""add vocabulary FSRS review state

Revision ID: d9a1b2c3e4f5
Revises: b4094f13a37a
Create Date: 2026-11-22 12:00:00.000000

additive：新增 ``vocabulary_review_state``（登录账号 × 词条 × 能力维度的
FSRS 调度状态），并为 ``review_fsrs`` 复习队列轮加部分唯一索引。

不回填、不改写既有 VocabularyAnswer / 错词历史计数 / 历史 session 快照；
downgrade 丢弃的是本批新增的调度状态，不影响首答统计与已发布快照。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "d9a1b2c3e4f5"
down_revision = "b4094f13a37a"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    op.create_table(
        "vocabulary_review_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("word_id", sa.Uuid(), nullable=False),
        sa.Column(
            "capability",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column(
            "state",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="new",
            nullable=False,
        ),
        sa.Column("stability", sa.Float(), server_default="0", nullable=False),
        sa.Column("difficulty", sa.Float(), server_default="5", nullable=False),
        sa.Column("reps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lapses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_rating",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=True,
        ),
        sa.Column("last_is_correct", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_vocabulary_review_state_tenant"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "word_id", "capability", name="uq_vocab_review_state_card"
        ),
    )
    op.create_index(
        "ix_vocabulary_review_state_tenant_id",
        "vocabulary_review_state",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocabulary_review_state_user_id",
        "vocabulary_review_state",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocabulary_review_state_word_id",
        "vocabulary_review_state",
        ["word_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocabulary_review_state_capability",
        "vocabulary_review_state",
        ["capability"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_review_state_due",
        "vocabulary_review_state",
        ["due_at"],
        unique=False,
    )
    # review_fsrs 复习队列轮：每学生至多一个进行中（与旧错词专项 review 分列）
    op.create_index(
        "uq_vocab_session_review_fsrs_active",
        "vocabulary_session",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text(
            "assignment_id IS NULL AND kind = 'review_fsrs' AND status = 'in_progress'"
        ),
    )

    # 多租户 C4a 同口径：ENABLE + FORCE RLS + tenant_isolation 策略
    # （缺上下文 NULL/'' 永不匹配，默认拒绝；与既有业务表一致）。
    op.execute("ALTER TABLE vocabulary_review_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vocabulary_review_state FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON vocabulary_review_state "
        "USING (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text) "
        "WITH CHECK (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text)"
    )


def downgrade():
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON vocabulary_review_state")
    op.execute("ALTER TABLE vocabulary_review_state NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE vocabulary_review_state DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "uq_vocab_session_review_fsrs_active", table_name="vocabulary_session"
    )
    op.drop_table("vocabulary_review_state")
