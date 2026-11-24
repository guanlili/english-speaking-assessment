"""AC4 内容治理迁移：存量回填口径隔离 schema 验证。

复用 test_vocab_position_migration 的隔离 schema 范式：在独立 schema 内
按「迁移前旧表结构」造存量数据，跑 ``ac4d5e6f7a80.upgrade()``，断言：
- active 词条 → approved + review_note=legacy，version=1；
- 非 active 词条保持 pending、不标 legacy；
- 演示种子库（title 以「演示」开头）source=demo，其余存量 source=import，
  未挂词库的词条回落 import；
- 审计表建成并纳入 RLS。
"""

import importlib
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlmodel import Session


def test_ac4_backfill_in_isolated_schema(db: Session) -> None:
    migration = importlib.import_module(
        "app.alembic.versions.ac4d5e6f7a80_vocab_content_review_gate"
    )
    schema = f"ac4_review_migration_{uuid.uuid4().hex}"
    engine = db.get_bind()
    assert isinstance(engine, Engine)

    demo_book = uuid.uuid4()
    normal_book = uuid.uuid4()
    w_demo = uuid.uuid4()
    w_normal = uuid.uuid4()
    w_archived = uuid.uuid4()
    w_orphan = uuid.uuid4()
    tenant_id = "00000000-0000-0000-0000-000000000001"
    user_id = uuid.uuid4()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            # 迁移前旧结构：词汇表尚无 AC4 六列
            connection.execute(
                text(
                    """
                    CREATE TABLE tenant (
                        id uuid PRIMARY KEY
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE "user" (
                        id uuid PRIMARY KEY
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE vocabulary_book (
                        id uuid PRIMARY KEY,
                        title varchar(255) NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE vocabulary_word (
                        id uuid PRIMARY KEY,
                        headword varchar(64) NOT NULL,
                        meaning_zh varchar(255) NOT NULL,
                        status varchar(16) NOT NULL DEFAULT 'active'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE vocabulary_book_item (
                        id uuid PRIMARY KEY,
                        book_id uuid NOT NULL,
                        word_id uuid NOT NULL,
                        position integer NOT NULL DEFAULT 0
                    )
                    """
                )
            )

            connection.execute(
                text("INSERT INTO tenant (id) VALUES (:id)"), {"id": tenant_id}
            )
            connection.execute(
                text('INSERT INTO "user" (id) VALUES (:id)'), {"id": user_id}
            )
            connection.execute(
                text("INSERT INTO vocabulary_book (id, title) VALUES (:id, :title)"),
                {"id": demo_book, "title": "演示入门词库"},
            )
            connection.execute(
                text("INSERT INTO vocabulary_book (id, title) VALUES (:id, :title)"),
                {"id": normal_book, "title": "普通班级词库"},
            )

            def insert_word(word_id: uuid.UUID, headword: str, status: str) -> None:
                connection.execute(
                    text(
                        "INSERT INTO vocabulary_word (id, headword, meaning_zh, status) "
                        "VALUES (:id, :head, :meaning, :status)"
                    ),
                    {
                        "id": word_id,
                        "head": headword,
                        "meaning": headword,
                        "status": status,
                    },
                )

            insert_word(w_demo, "demo01", "active")
            insert_word(w_normal, "normal01", "active")
            insert_word(w_archived, "arch01", "archived")
            insert_word(w_orphan, "orphan01", "active")

            connection.execute(
                text(
                    "INSERT INTO vocabulary_book_item (id, book_id, word_id, position) "
                    "VALUES (:id, :book, :word, 1)"
                ),
                {"id": uuid.uuid4(), "book": demo_book, "word": w_demo},
            )
            connection.execute(
                text(
                    "INSERT INTO vocabulary_book_item (id, book_id, word_id, position) "
                    "VALUES (:id, :book, :word, 1)"
                ),
                {"id": uuid.uuid4(), "book": normal_book, "word": w_normal},
            )
            connection.execute(
                text(
                    "INSERT INTO vocabulary_book_item (id, book_id, word_id, position) "
                    "VALUES (:id, :book, :word, 1)"
                ),
                {"id": uuid.uuid4(), "book": normal_book, "word": w_archived},
            )

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            def row(word_id: uuid.UUID) -> dict:
                return dict(
                    connection.execute(
                        text(
                            "SELECT review_status, review_note, source, version "
                            "FROM vocabulary_word WHERE id = :id"
                        ),
                        {"id": word_id},
                    )
                    .mappings()
                    .one()
                )

            demo = row(w_demo)
            assert demo["review_status"] == "approved"
            assert demo["review_note"] == "legacy"
            assert demo["source"] == "demo"
            assert demo["version"] == 1

            normal = row(w_normal)
            assert normal["review_status"] == "approved"
            assert normal["review_note"] == "legacy"
            assert normal["source"] == "import"
            assert normal["version"] == 1

            archived = row(w_archived)
            assert archived["review_status"] == "pending"
            assert archived["review_note"] is None
            assert archived["source"] == "import"

            orphan = row(w_orphan)
            assert orphan["review_status"] == "approved"
            assert orphan["review_note"] == "legacy"
            assert orphan["source"] == "import"

            # 审计表建成且 RLS 已启用/强制（限定本 schema，避开 public 同名表）
            rls = connection.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relname = 'vocabulary_content_review_audit' "
                    "AND n.nspname = :schema"
                ),
                {"schema": schema},
            ).one()
            assert rls[0] is True
            assert rls[1] is True
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            transaction.commit()
