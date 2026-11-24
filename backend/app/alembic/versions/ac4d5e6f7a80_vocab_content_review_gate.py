"""vocabulary content review governance (AC4)

Revision ID: ac4d5e6f7a80
Revises: e9a7c3f1d5b2
Create Date: 2026-11-24 18:00:00.000000

词条内容治理：
- ``vocabulary_word`` 新增 source / review_status / reviewer_id / reviewed_at /
  review_note / version；
- 新增 ``vocabulary_content_review_audit`` 审核审计表（逐词留痕通过/拒绝/回退），
  纳入多租户 RLS（FORCE RLS + tenant_isolation）；
- 存量回填：active 词条 → approved + note=legacy；非 active 保持 pending；
  演示种子库（book title 以「演示」开头）source=demo，其余 source=import；
  version=1。

不改动任何已发布任务快照；存量作答与历史报告仍按快照解释。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "ac4d5e6f7a80"
down_revision = "e9a7c3f1d5b2"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

AUDIT_TABLE = "vocabulary_content_review_audit"

POLICY = (
    "coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text"
)


def upgrade():
    # ── 词条审核字段 ────────────────────────────────────────────────
    op.add_column(
        "vocabulary_word",
        sa.Column(
            "source",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="teacher",
            nullable=False,
        ),
    )
    op.add_column(
        "vocabulary_word",
        sa.Column(
            "review_status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "vocabulary_word",
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "vocabulary_word",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vocabulary_word",
        sa.Column("review_note", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
    )
    op.add_column(
        "vocabulary_word",
        sa.Column(
            "version", sa.Integer(), server_default="1", nullable=False
        ),
    )
    op.create_foreign_key(
        "fk_vocab_word_reviewer",
        "vocabulary_word",
        "user",
        ["reviewer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_vocabulary_word_source", "vocabulary_word", ["source"], unique=False
    )
    op.create_index(
        "ix_vocabulary_word_review_status",
        "vocabulary_word",
        ["review_status"],
        unique=False,
    )
    op.create_index(
        "ix_vocabulary_word_reviewer_id",
        "vocabulary_word",
        ["reviewer_id"],
        unique=False,
    )

    # ── 存量回填 ────────────────────────────────────────────────────
    # active → approved + legacy 留痕；非 active 保持 pending，不标 legacy。
    op.execute(
        sa.text(
            """
            UPDATE vocabulary_word
            SET review_status = CASE WHEN status = 'active' THEN 'approved' ELSE 'pending' END,
                review_note = CASE WHEN status = 'active' THEN 'legacy' ELSE NULL END,
                version = 1
            """
        )
    )
    # 演示种子库（title 以「演示」开头）→ demo；其余存量 → import；
    # 未挂任何词库的词条回落 import。
    op.execute(
        sa.text(
            """
            UPDATE vocabulary_word w
            SET source = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM vocabulary_book_item i
                    JOIN vocabulary_book b ON b.id = i.book_id
                    WHERE i.word_id = w.id AND b.title LIKE '演示%'
                ) THEN 'demo'
                ELSE 'import'
            END
            """
        )
    )

    # ── 审核审计表 ──────────────────────────────────────────────────
    op.create_table(
        AUDIT_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        # 不做级联删除：词条归档/移出词库不抹掉历史审核记录
        sa.Column("word_id", sa.Uuid(), nullable=False),
        sa.Column("headword", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=True),
        sa.Column("actor_role", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("from_status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("to_status", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_vocab_review_audit_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vocab_review_audit_tenant_id",
        AUDIT_TABLE,
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_review_audit_word_id",
        AUDIT_TABLE,
        ["word_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_review_audit_actor_id",
        AUDIT_TABLE,
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_review_audit_action",
        AUDIT_TABLE,
        ["action"],
        unique=False,
    )

    # 多租户 RLS（与既有业务表同口径）
    op.execute(f"ALTER TABLE {AUDIT_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {AUDIT_TABLE} "
        f"USING ({POLICY}) WITH CHECK ({POLICY})"
    )


def downgrade():
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {AUDIT_TABLE}")
    op.execute(f"ALTER TABLE {AUDIT_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {AUDIT_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_vocab_review_audit_action", table_name=AUDIT_TABLE)
    op.drop_index("ix_vocab_review_audit_actor_id", table_name=AUDIT_TABLE)
    op.drop_index("ix_vocab_review_audit_word_id", table_name=AUDIT_TABLE)
    op.drop_index("ix_vocab_review_audit_tenant_id", table_name=AUDIT_TABLE)
    op.drop_table(AUDIT_TABLE)

    op.drop_index("ix_vocabulary_word_reviewer_id", table_name="vocabulary_word")
    op.drop_index("ix_vocabulary_word_review_status", table_name="vocabulary_word")
    op.drop_index("ix_vocabulary_word_source", table_name="vocabulary_word")
    op.drop_constraint("fk_vocab_word_reviewer", "vocabulary_word", type_="foreignkey")
    op.drop_column("vocabulary_word", "version")
    op.drop_column("vocabulary_word", "review_note")
    op.drop_column("vocabulary_word", "reviewed_at")
    op.drop_column("vocabulary_word", "reviewer_id")
    op.drop_column("vocabulary_word", "review_status")
    op.drop_column("vocabulary_word", "source")
