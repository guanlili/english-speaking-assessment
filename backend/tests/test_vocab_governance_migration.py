"""#517 版权台账 + 版本历史迁移：存量回填口径隔离 schema 验证。

在独立 schema 内按迁移前旧表结构造存量数据，跑
``b6c7d8e9f0a1.upgrade()``，断言：
- 词条 source_type 映射：textbook→textbook、ai→ai、demo→demo、
  其余（teacher/import 等）→self_built；
- 词库统一回填 self_built；
- ``vocabulary_license_audit`` / ``vocabulary_book_version`` 建成并
  ENABLE + FORCE RLS + ``tenant_isolation`` 策略。
"""

import importlib
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlmodel import Session


def test_governance_backfill_in_isolated_schema(db: Session) -> None:
    migration = importlib.import_module(
        "app.alembic.versions.b6c7d8e9f0a1_vocab_governance"
    )
    schema = f"gov_migration_{uuid.uuid4().hex}"
    engine = db.get_bind()
    assert isinstance(engine, Engine)

    book_id = uuid.uuid4()
    w_textbook = uuid.uuid4()
    w_ai = uuid.uuid4()
    w_demo = uuid.uuid4()
    w_teacher = uuid.uuid4()
    w_import = uuid.uuid4()
    tenant_id = "00000000-0000-0000-0000-000000000001"
    user_id = uuid.uuid4()

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("CREATE TABLE tenant (id uuid PRIMARY KEY)"))
            connection.execute(text('CREATE TABLE "user" (id uuid PRIMARY KEY)'))
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
                        source varchar(16) NOT NULL DEFAULT 'teacher',
                        status varchar(16) NOT NULL DEFAULT 'active'
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
                {"id": book_id, "title": "回填词库"},
            )

            def insert_word(word_id: uuid.UUID, source: str) -> None:
                connection.execute(
                    text(
                        "INSERT INTO vocabulary_word "
                        "(id, headword, meaning_zh, source) "
                        "VALUES (:id, :head, :meaning, :source)"
                    ),
                    {
                        "id": word_id,
                        "head": source,
                        "meaning": source,
                        "source": source,
                    },
                )

            insert_word(w_textbook, "textbook")
            insert_word(w_ai, "ai")
            insert_word(w_demo, "demo")
            insert_word(w_teacher, "teacher")
            insert_word(w_import, "import")

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            def word_type(word_id: uuid.UUID) -> str:
                return connection.execute(
                    text("SELECT source_type FROM vocabulary_word WHERE id = :id"),
                    {"id": word_id},
                ).scalar_one()

            assert word_type(w_textbook) == "textbook"
            assert word_type(w_ai) == "ai"
            assert word_type(w_demo) == "demo"
            assert word_type(w_teacher) == "self_built"
            assert word_type(w_import) == "self_built"

            book_type = connection.execute(
                text("SELECT source_type FROM vocabulary_book WHERE id = :id"),
                {"id": book_id},
            ).scalar_one()
            assert book_type == "self_built"

            for table in ("vocabulary_license_audit", "vocabulary_book_version"):
                rls = connection.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relname = :table AND n.nspname = :schema"
                    ),
                    {"table": table, "schema": schema},
                ).one()
                assert rls[0] is True
                assert rls[1] is True
                policy = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_policies "
                        "WHERE schemaname = :schema AND tablename = :table "
                        "AND policyname = 'tenant_isolation'"
                    ),
                    {"schema": schema, "table": table},
                ).scalar_one()
                assert policy == 1
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            transaction.commit()
