"""应用引擎空闲事务超时（#517 容量项）：配置下发、超时后可恢复、并发提交不丢作答、并发会话不串租户。

口径：
- 超时参数只挂在应用业务/平台通道引擎（``core.db``）；Alembic 迁移与
  admin/owner 管理连接走独立引擎，不在本文件覆盖范围。
- 测试库为本地隔离库（conftest 自动建/清），不触开发/生产库。
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import InternalError
from sqlalchemy.pool import NullPool
from sqlmodel import Session, col, select

from app.core import db as db_module
from app.core.config import settings
from app.core.db import _idle_txn_connect_args
from app.core.tenant_context import tenant_scope
from app.models import Attempt


def _fresh_engine(**overrides):
    """按测试库 URI 建独立引擎（NullPool，用完即 dispose），便于挂自定义连接参数。"""
    kwargs: dict[str, object] = {
        "poolclass": NullPool,
        "pool_pre_ping": True,
        "connect_args": _idle_txn_connect_args(),
    }
    kwargs.update(overrides)
    return create_engine(str(settings.SQLALCHEMY_DATABASE_TEST_URI), **kwargs)


def test_connect_args_carry_configured_timeout() -> None:
    """默认 30s → options 下发 30000ms；置 0 时关闭（无 options）。"""
    args = _idle_txn_connect_args()
    assert "idle_in_transaction_session_timeout=30000" in args["options"]

    settings.DB_IDLE_IN_TXN_TIMEOUT_S = 0
    try:
        assert _idle_txn_connect_args() == {}
    finally:
        settings.DB_IDLE_IN_TXN_TIMEOUT_S = 30


def test_idle_timeout_visible_on_live_connection() -> None:
    """新连接上 PG 的 idle_in_transaction_session_timeout 与配置一致。"""
    engine = _fresh_engine()
    try:
        with engine.connect() as conn:
            # pg_settings.setting 是原始毫秒值（current_setting/SHOW 会格式化成
            # 「30s」间隔文本，不便直接比较）
            value = conn.execute(
                text(
                    "SELECT setting FROM pg_settings "
                    "WHERE name = 'idle_in_transaction_session_timeout'"
                )
            ).scalar_one()
            assert str(value) == "30000"
    finally:
        engine.dispose()


def test_idle_transaction_killed_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """事务挂起超过超时被 PG 终止；后续新连接可正常工作（pre-ping 不残留死连接）。"""
    monkeypatch.setattr(settings, "DB_IDLE_IN_TXN_TIMEOUT_S", 1)
    engine = _fresh_engine()
    try:
        conn = engine.connect()
        conn.execute(text("BEGIN"))
        # 超过 1s 空闲事务超时；PG 终止后端连接
        time.sleep(1.6)
        with pytest.raises(InternalError):
            conn.execute(text("SELECT 1"))
        conn.close()

        # 恢复：全新连接查询正常，不被上一条死连接连累
        with engine.connect() as conn2:
            assert conn2.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_concurrent_commits_do_not_lose_answers(db: Session) -> None:
    """两线程并发各提交 5 条作答记录：全部落库，无丢失、无串键。"""
    engine = db_module.engine
    n = 5
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(tag: str) -> None:
        try:
            with Session(engine) as session:
                barrier.wait()
                for i in range(n):
                    session.add(
                        Attempt(
                            item_type="question",
                            item_id=uuid.uuid4(),
                            duration_s=3.0,
                            audio_path=f"idle-timeout-probe/{tag}-{i}.webm",
                            idempotency_key=f"idle-timeout-probe-{tag}-{i}",
                        )
                    )
                session.commit()
        except Exception as exc:  # noqa: BLE001 - 收集后断言失败原因
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, [str(e) for e in errors]
    keys = [f"idle-timeout-probe-{tag}-{i}" for tag in ("a", "b") for i in range(n)]
    rows = db.exec(
        select(Attempt).where(col(Attempt.idempotency_key).in_(keys))  # type: ignore[attr-defined]
    ).all()
    assert len(rows) == 2 * n


def test_concurrent_sessions_do_not_leak_tenant_context(db: Session) -> None:
    """并发会话各绑各的租户上下文：事务内 current_setting 互不串扰。"""
    engine = db_module.engine
    tid_a = uuid.uuid4()
    tid_b = uuid.uuid4()
    seen: dict[str, str | None] = {}
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def worker(tid: uuid.UUID, key: str) -> None:
        try:
            with tenant_scope(tid):
                with Session(engine) as session:
                    barrier.wait()
                    seen[key] = (
                        session.connection()
                        .execute(text("SELECT current_setting('app.tenant_id', true)"))
                        .scalar_one()
                    )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    ta = threading.Thread(target=worker, args=(tid_a, "a"))
    tb = threading.Thread(target=worker, args=(tid_b, "b"))
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    assert not errors, [str(e) for e in errors]
    assert seen["a"] == str(tid_a)
    assert seen["b"] == str(tid_b)
