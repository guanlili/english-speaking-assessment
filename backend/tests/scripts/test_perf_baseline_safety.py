"""perf_baseline 安全闸测试（返修R02）：危险配置拒绝、既有库拒绝、
绝不无提示 DROP。用假 engine 工厂捕获 SQL，不实际连库执行危险 DDL。"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import perf_baseline as perf  # ty: ignore[unresolved-import]  # noqa: E402

from app.core.config import settings  # noqa: E402


class _FakeCursor:
    def __init__(self, statements: list[str]) -> None:
        self.statements = statements
        self._result: list = []

    def execute(self, statement, parameters=None):
        text = str(statement)
        self.statements.append(text)
        if "pg_database" in text and "CREATE" not in text.upper():
            # 存在性检查：由测试通过 exists 控制
            self._result = [[1]] if self._cursor_exists else []
        else:
            self._result = []

    _cursor_exists = False

    def fetchall(self):
        return self._result

    def scalar(self):
        return self._result[0][0] if self._result else None

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, statements: list[str], cursor: _FakeCursor) -> None:
        self.statements = statements
        self._cursor = cursor

    def execute(self, statement, parameters=None):
        return self._cursor.execute(statement, parameters) or self._cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.cursor = _FakeCursor(self.statements)
        self.connections: list[_FakeConnection] = []

    def connect(self):
        conn = _FakeConnection(self.statements, self.cursor)
        self.connections.append(conn)
        return conn

    def dispose(self):
        pass


def test_refuses_non_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(SystemExit, match="local"):
        perf._refuse_unsafe_target()


def test_refuses_remote_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "POSTGRES_SERVER", "db.prod.example.com")
    with pytest.raises(SystemExit, match="不是本机"):
        perf._refuse_unsafe_target()


def test_refuses_name_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "POSTGRES_SERVER", "localhost")
    monkeypatch.setattr(settings, "POSTGRES_DB_TEST", perf.PERF_DB_NAME)
    with pytest.raises(SystemExit, match="冲突"):
        perf._refuse_unsafe_target()


def test_prepare_refuses_existing_db_without_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同名既有库：拒绝且不执行任何 CREATE/DROP（R02 核心）。"""
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "POSTGRES_SERVER", "localhost")
    fake = _FakeEngine()
    fake.cursor._cursor_exists = True  # app_perf 已存在

    def factory(uri, **kwargs):
        return fake

    with pytest.raises(SystemExit, match="已存在"):
        perf._prepare_database(create_engine_fn=factory)
    ddl = [s for s in fake.statements if "CREATE DATABASE" in s or "DROP" in s.upper()]
    assert ddl == [], f"拒绝路径不得执行任何建/删库 DDL: {ddl}"


def test_prepare_creates_when_absent_and_never_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    monkeypatch.setattr(settings, "POSTGRES_SERVER", "localhost")
    fake = _FakeEngine()
    fake.cursor._cursor_exists = False

    def factory(uri, **kwargs):
        return fake

    engine, created = perf._prepare_database(create_engine_fn=factory)
    assert created is True
    assert any("CREATE DATABASE" in s for s in fake.statements)
    # 准备阶段绝不出现 DROP（删除只发生在成功运行后的 finally）
    assert not any("DROP" in s.upper() for s in fake.statements)
