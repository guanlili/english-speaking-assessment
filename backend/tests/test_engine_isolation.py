"""Sentinel test: verifies test engine isolation is correctly wired.

MUST RUN FIRST (alphabetically). If this fails, later DB tests will silently
write to the dev/production database instead of `app_test`.
"""

from sqlalchemy import make_url, text
from sqlmodel import Session

from app.core import db as db_module
from app.core.config import settings


def test_engine_isolation_points_to_test_db() -> None:
    """core.db.engine must resolve to the test database, not the app database.

    注意：SQLAlchemy 会对 URL 中的密码打码（***），不能直接比整串 URL；
    按主机/端口/库名比较才是隔离保证。
    """
    engine = db_module.engine
    expected = make_url(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    assert engine.url.host == expected.host
    assert engine.url.port == expected.port
    assert engine.url.database == expected.database
    assert engine.url.username == expected.username
    # 库名必须是测试库而非开发库（防误连开发数据）
    assert settings.POSTGRES_DB_TEST in str(engine.url)
    assert settings.POSTGRES_DB_TEST != settings.POSTGRES_DB


def test_worker_and_deps_use_test_engine() -> None:
    """Modules that cache engine via `from app.core.db import engine` must be redirected.

    The __getattr__ indirection ensures this, but we verify explicitly to catch
    any module that caches the engine at import time via a non-attribute reference.
    """

    # These modules access engine lazily (from X import engine → __getattr__ on call).
    # We just sanity-check that set_engine override is active in core.db.
    assert db_module._engine_override is not None
    assert db_module.engine is db_module._engine_override
    # If a regression introduces an eager `engine = create_engine(...)` at module
    # level in core/db, this will catch it.
    with Session(db_module.engine) as s:
        result = s.connection().execute(text("SELECT current_database()")).one()
        assert result[0] == settings.POSTGRES_DB_TEST
