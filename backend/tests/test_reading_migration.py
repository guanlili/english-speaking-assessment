"""旧版平铺拆分的归属迁移：仅完整且唯一的匹配可归回文章。"""

import importlib
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlmodel import Session


def test_reading_migration_preserves_ids_and_skips_ambiguous_matches(
    db: Session,
) -> None:
    migration = importlib.import_module(
        "app.alembic.versions.60b66752e050_keep_reading_sentences_under_parent_"
    )
    schema = f"reading_migration_{uuid.uuid4().hex}"
    # conftest 的 engine 只连接 app_test；在事务内的独立 schema 验证真实 DDL。
    engine = db.get_bind()
    assert isinstance(engine, Engine)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text("""
                CREATE TABLE passage (
                    id uuid PRIMARY KEY, title text NOT NULL, text text NOT NULL,
                    topic text NOT NULL DEFAULT 'Pets', cefr_band text NOT NULL DEFAULT 'B1',
                    unit_id uuid, is_active boolean NOT NULL, created_at timestamptz
                )
            """)
            )
            ids: dict[str, uuid.UUID] = {}

            def add(key: str, title: str, body: str, active: bool) -> None:
                ids[key] = uuid.uuid4()
                connection.execute(
                    text(
                        "INSERT INTO passage (id,title,text,is_active,created_at) VALUES (:id,:title,:body,:active,'2026-10-01')"
                    ),
                    {"id": ids[key], "title": title, "body": body, "active": active},
                )

            add("parent", "Article", "First sentence.\nSecond sentence.", False)
            add("first", "Article（一）", "First sentence.", True)
            add("second", "Article（二）", "Second sentence.", True)
            add("ambiguous", "Ambiguous", "One.\nTwo.", False)
            add("one", "Ambiguous（一）", "One.", True)
            add("duplicate", "Ambiguous（一）", "One.", True)
            add("two", "Ambiguous（二）", "Two.", True)
            add("partial", "Partial", "Three.\nFour.", False)
            add("three", "Partial（一）", "Three.", True)
            add("unrelated", "Article（三）", "Unrelated independent article.", True)
            add(
                "sentence_parent",
                "Sentence Article",
                "Hello there. How are you? Goodbye!",
                False,
            )
            add("s1", "Sentence Article（一）", "Hello there.", True)
            add("s2", "Sentence Article（二）", "How are you?", True)
            add("s3", "Sentence Article（三）", "Goodbye!", True)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            rows = {
                row["id"]: row
                for row in connection.execute(text("SELECT * FROM passage")).mappings()
            }
            assert set(rows) == set(ids.values())  # 不删除/重建旧题目，历史 ID 保留
            assert rows[ids["parent"]]["reading_split"] is True
            assert rows[ids["parent"]]["is_active"] is True
            for key in ("first", "second"):
                assert rows[ids[key]]["parent_passage_id"] == ids["parent"]
                assert rows[ids[key]]["is_active"] is False
            assert rows[ids["sentence_parent"]]["reading_split"] is True
            for key in ("s1", "s2", "s3"):
                assert rows[ids[key]]["parent_passage_id"] == ids["sentence_parent"]
                assert rows[ids[key]]["is_active"] is False
            for key in (
                "ambiguous",
                "one",
                "duplicate",
                "two",
                "partial",
                "three",
                "unrelated",
            ):
                assert rows[ids[key]]["parent_passage_id"] is None
                assert rows[ids[key]]["reading_split"] is False
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            rows = {
                row["id"]: row
                for row in connection.execute(text("SELECT * FROM passage")).mappings()
            }
            assert rows[ids["parent"]]["is_active"] is False
            assert rows[ids["first"]]["is_active"] is True
            assert "parent_passage_id" not in rows[ids["parent"]]
        finally:
            transaction.rollback()
