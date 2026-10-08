"""vocab_book_item position 平局回填：整本书重排为连续稳定顺序。"""

import importlib
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlmodel import Session


def test_position_backfill_renumbers_ties_and_keeps_real_order(db: Session) -> None:
    migration = importlib.import_module(
        "app.alembic.versions.c4e8f9a21b76_backfill_vocab_book_item_position"
    )
    schema = f"vocab_pos_migration_{uuid.uuid4().hex}"
    engine = db.get_bind()
    assert isinstance(engine, Engine)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(
                text("""
                CREATE TABLE vocabulary_book_item (
                    id uuid PRIMARY KEY,
                    book_id uuid NOT NULL,
                    word_id uuid NOT NULL,
                    position integer NOT NULL DEFAULT 0
                )
            """)
            )
            book_a, book_b = uuid.uuid4(), uuid.uuid4()

            def add(book: uuid.UUID, position: int) -> uuid.UUID:
                item_id = uuid.uuid4()
                connection.execute(
                    text(
                        "INSERT INTO vocabulary_book_item (id, book_id, word_id, position) "
                        "VALUES (:id, :book, :word, :position)"
                    ),
                    {
                        "id": item_id,
                        "book": book,
                        "word": uuid.uuid4(),
                        "position": position,
                    },
                )
                return item_id

            # 书 A：历史平局数据（建库带词漏传 position，全 0）
            add(book_a, 0)
            add(book_a, 0)
            add(book_a, 0)
            # 书 B：真实 legacy 形态——建库全 0，之后追加词从 max(0)+1=1 起
            # 落位（追加词与零值撞位，同样平局）
            b1, b2, b3 = add(book_b, 0), add(book_b, 0), add(book_b, 0)
            b4, b5 = add(book_b, 1), add(book_b, 2)

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            def rows(book: uuid.UUID) -> list[tuple[uuid.UUID, int]]:
                return [
                    (row[0], row[1])
                    for row in connection.execute(
                        text(
                            "SELECT id, position FROM vocabulary_book_item "
                            "WHERE book_id = :book ORDER BY position"
                        ),
                        {"book": book},
                    )
                ]

            # 书 A：0,0,0 → 连续 1,2,3（不再平局，顺序稳定）
            assert [pos for _id, pos in rows(book_a)] == [1, 2, 3]
            # 书 B：建库词（ctid 物理序≈插入序）在前、追加词在后，紧密 1..5
            assert [(i, pos) for i, pos in rows(book_b)] == [
                (b1, 1),
                (b2, 2),
                (b3, 3),
                (b4, 4),
                (b5, 5),
            ]
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            transaction.commit()
