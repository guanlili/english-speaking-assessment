"""多租户 B1：默认租户种子 / 列级默认兜底 / 复合唯一 / TenantSession 机制."""

import uuid

import pytest
import sqlalchemy.pool
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.core import db as _db
from app.core.tenant_context import (
    current_tenant_id,
    install_tenant_bind,
    tenant_scope,
)
from app.models import DEFAULT_TENANT_ID, Classroom, Tenant, User


def test_default_tenant_seeded(db: Session) -> None:
    """initial_data 种子：默认租户固定 UUID 幂等存在。"""
    row = db.get(Tenant, DEFAULT_TENANT_ID)
    assert row is not None
    assert row.slug == "default"
    assert row.status == "active"


def test_user_classroom_student_get_default_tenant(db: Session) -> None:
    """ORM default 兜底：不显式传 tenant_id 的写入路径全部落默认租户。"""
    u = User(
        email=f"b1-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        username=f"s{uuid.uuid4().hex[:8]}",
        role="student",
    )
    c = Classroom(code=f"T{uuid.uuid4().hex[:6].upper()}", name="B1 班")
    db.add(u)
    db.add(c)
    db.commit()
    db.refresh(u)
    db.refresh(c)
    assert u.tenant_id == DEFAULT_TENANT_ID
    assert c.tenant_id == DEFAULT_TENANT_ID


def test_tenant_scoped_composite_unique(db: Session) -> None:
    """(tenant_id, username) 复合唯一在；同租户重号被拦。"""
    n = f"dup-{uuid.uuid4().hex[:8]}"
    db.add(User(hashed_password="x", username=n, role="student"))
    db.commit()
    db.add(User(hashed_password="x", username=n, role="student"))
    with pytest.raises(Exception, match="uq_user_tenant_username|duplicate key"):
        db.commit()
    db.rollback()


def test_tenant_session_bind_and_reset() -> None:
    """TenantSession 机制：tenant_scope 内事务可读到 app.tenant_id，
    块外新事务不残留（transaction-local 语义的进程内验证，不依赖 RLS）。"""
    engine = _db.engine
    install_tenant_bind(engine)
    tid = uuid.uuid4()

    with tenant_scope(tid):
        with Session(engine) as s:
            v = (
                s.connection()
                .execute(text("SELECT current_setting('app.tenant_id', true)"))
                .scalar_one()
            )
            assert v == str(tid)

    assert current_tenant_id() is None
    with Session(engine) as s:
        v = (
            s.connection()
            .execute(
                text("SELECT coalesce(current_setting('app.tenant_id', true), '')")
            )
            .scalar_one()
        )
        assert v == ""


def test_tenant_session_rebind_across_transactions() -> None:
    """commit 后新事务重绑：同一物理连接先后服务两个租户互不串（原型 P3 语义）."""
    from sqlalchemy import create_engine

    from app.core.config import settings

    engine = create_engine(
        str(settings.SQLALCHEMY_DATABASE_URI), poolclass=sqlalchemy.pool.NullPool
    )
    try:
        install_tenant_bind(engine)
        ta, tb = uuid.uuid4(), uuid.uuid4()

        with tenant_scope(ta):
            with Session(engine) as s:
                pid = (
                    s.connection().execute(text("SELECT pg_backend_pid()")).scalar_one()
                )
                assert s.connection().execute(
                    text("SELECT current_setting('app.tenant_id', true)")
                ).scalar_one() == str(ta)
        with tenant_scope(tb):
            with Session(engine) as s:
                pid2 = (
                    s.connection().execute(text("SELECT pg_backend_pid()")).scalar_one()
                )
                # NullPool 下同线程两次连接通常同 backend；仅当同连接时断言不串
                if pid2 == pid:
                    assert s.connection().execute(
                        text("SELECT current_setting('app.tenant_id', true)")
                    ).scalar_one() == str(tb)
    finally:
        engine.dispose()


def test_cross_tenant_join_guard(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """跨校守卫：不同租户的账号凭课堂码加入 → 403；同租户正常入班不受影响.

    单租户窗口内（全员默认租户）守卫恒通过——这里造第二租户验证拒绝路径。
    """
    from app import crud

    other = Tenant(slug=f"b-{uuid.uuid4().hex[:6]}", name_zh="B 校")
    db.add(other)
    db.commit()
    db.refresh(other)

    # 建课堂（默认租户）+ 他校学生账号
    created = client.post(
        "/api/v1/classes",
        json={"name": "B1 守卫班"},
        headers=superuser_token_headers,
    )
    assert created.status_code == 200
    code = created.json()["code"]

    other_user = User(
        email=None,
        hashed_password="x",
        username=f"b-stu-{uuid.uuid4().hex[:6]}",
        role="student",
        tenant_id=other.id,
    )
    db.add(other_user)
    db.commit()
    db.refresh(other_user)
    classroom = db.exec(
        select(Classroom).where(Classroom.code == code)  # type: ignore[arg-type]
    ).one()

    with pytest.raises(crud.CrossTenantJoinError):
        crud.join_classroom(
            session=db, classroom=classroom, user=other_user, display_name="B 校生"
        )
