"""vocabulary license ledger + book version history (#517)

Revision ID: b6c7d8e9f0a1
Revises: f8a2b3c4d5e6
Create Date: 2026-11-25 12:00:00.000000

版权/授权台账：
- ``vocabulary_book`` / ``vocabulary_word`` 各新增 source_type 与授权元数据列；
  原 ``source`` 列保留兼容不删除。存量映射：textbook→textbook、ai→ai、
  demo→demo、其他→self_built；词库统一回填 self_built。
- 新增 ``vocabulary_license_audit``：授权变更前后值快照留痕（actor/租户/时间）。

版本历史与回滚：
- 新增 ``vocabulary_book_version``：词条集合内容快照 + 确定性内容哈希 +
  操作人/动作/摘要/租户；回滚只生成新版本，不删历史；不改写任何
  ``vocabulary_assignment.snapshot_items``。

两张新表均 ENABLE + FORCE RLS + ``tenant_isolation`` 策略，纳入 RLS_TABLES。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a1"
down_revision = "f8a2b3c4d5e6"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

LICENSE_AUDIT_TABLE = "vocabulary_license_audit"
BOOK_VERSION_TABLE = "vocabulary_book_version"

POLICY = "coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text"


def _license_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "source_type",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="self_built",
            nullable=False,
        ),
        sa.Column(
            "license_owner",
            sqlmodel.sql.sqltypes.AutoString(length=120),
            nullable=True,
        ),
        sa.Column(
            "license_ref",
            sqlmodel.sql.sqltypes.AutoString(length=120),
            nullable=True,
        ),
        sa.Column("license_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "authorization_doc_url",
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True,
        ),
        sa.Column(
            "license_note",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
    ]


def upgrade():
    # ── 词库 / 词条授权列 ──────────────────────────────────────────
    for table in ("vocabulary_word", "vocabulary_book"):
        for column in _license_columns():
            op.add_column(table, column)
        op.create_index(
            f"ix_{table}_source_type",
            table,
            ["source_type"],
            unique=False,
        )

    # 存量回填：词条按原 source 映射；词库统一 self_built。
    op.execute(
        sa.text(
            """
            UPDATE vocabulary_word
            SET source_type = CASE source
                WHEN 'textbook' THEN 'textbook'
                WHEN 'ai' THEN 'ai'
                WHEN 'demo' THEN 'demo'
                ELSE 'self_built'
            END
            """
        )
    )
    op.execute(
        sa.text(
            "UPDATE vocabulary_book SET source_type = 'self_built' "
            "WHERE source_type IS NULL"
        )
    )

    # ── 授权变更审计表 ─────────────────────────────────────────────
    op.create_table(
        LICENSE_AUDIT_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column(
            "target_type",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column("book_id", sa.Uuid(), nullable=True),
        sa.Column("word_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "actor_name",
            sqlmodel.sql.sqltypes.AutoString(length=120),
            nullable=True,
        ),
        sa.Column(
            "actor_role",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=True,
        ),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column(
            "note",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["vocabulary_book.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["word_id"], ["vocabulary_word.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_vocab_license_audit_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vocab_license_audit_tenant_created_at",
        LICENSE_AUDIT_TABLE,
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_license_audit_target_type",
        LICENSE_AUDIT_TABLE,
        ["target_type"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_license_audit_book_id",
        LICENSE_AUDIT_TABLE,
        ["book_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_license_audit_word_id",
        LICENSE_AUDIT_TABLE,
        ["word_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_license_audit_actor_id",
        LICENSE_AUDIT_TABLE,
        ["actor_id"],
        unique=False,
    )

    # ── 词库版本快照表 ─────────────────────────────────────────────
    op.create_table(
        BOOK_VERSION_TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "content_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "actor_name",
            sqlmodel.sql.sqltypes.AutoString(length=120),
            nullable=True,
        ),
        sa.Column(
            "actor_role",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=True,
        ),
        sa.Column(
            "action",
            sqlmodel.sql.sqltypes.AutoString(length=24),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["vocabulary_book.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
            name="fk_vocab_book_version_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "version_no", name="uq_vocab_book_version_no"),
    )
    op.create_index(
        "ix_vocab_book_version_tenant_created_at",
        BOOK_VERSION_TABLE,
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_book_version_book_id",
        BOOK_VERSION_TABLE,
        ["book_id"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_book_version_content_hash",
        BOOK_VERSION_TABLE,
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "ix_vocab_book_version_action",
        BOOK_VERSION_TABLE,
        ["action"],
        unique=False,
    )

    # 多租户 RLS（与既有业务表同口径）
    for table in (LICENSE_AUDIT_TABLE, BOOK_VERSION_TABLE):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({POLICY}) WITH CHECK ({POLICY})"
        )


def downgrade():
    for table in (LICENSE_AUDIT_TABLE, BOOK_VERSION_TABLE):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_vocab_book_version_action", table_name=BOOK_VERSION_TABLE)
    op.drop_index("ix_vocab_book_version_content_hash", table_name=BOOK_VERSION_TABLE)
    op.drop_index("ix_vocab_book_version_book_id", table_name=BOOK_VERSION_TABLE)
    op.drop_index(
        "ix_vocab_book_version_tenant_created_at", table_name=BOOK_VERSION_TABLE
    )
    op.drop_table(BOOK_VERSION_TABLE)

    op.drop_index("ix_vocab_license_audit_actor_id", table_name=LICENSE_AUDIT_TABLE)
    op.drop_index("ix_vocab_license_audit_word_id", table_name=LICENSE_AUDIT_TABLE)
    op.drop_index("ix_vocab_license_audit_book_id", table_name=LICENSE_AUDIT_TABLE)
    op.drop_index("ix_vocab_license_audit_target_type", table_name=LICENSE_AUDIT_TABLE)
    op.drop_index(
        "ix_vocab_license_audit_tenant_created_at", table_name=LICENSE_AUDIT_TABLE
    )
    op.drop_table(LICENSE_AUDIT_TABLE)

    for table in ("vocabulary_word", "vocabulary_book"):
        op.drop_index(f"ix_{table}_source_type", table_name=table)
        for column in (
            "license_note",
            "authorization_doc_url",
            "license_expires_at",
            "license_ref",
            "license_owner",
            "source_type",
        ):
            op.drop_column(table, column)
