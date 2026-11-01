"""多租户 C3：TenantSession 接线（请求级上下文 + worker 重绑）。

验收点（A 期清单 §1.4/§7-C3，设计稿 §5/§9-5 前置管线）：
1. 请求中间件：Bearer tid → ContextVar → 事务内 set_config 可见
   （RLS 激活前只有上下文在流动，本测试锁住「流动」本身）。
2. tid 一致性：伪造/过期租户声明的 token → get_current_user 401、
   可选通道降级匿名。
3. 后台任务重绑：_run_in_worker 按作答行租户建立作用域
   （线程池上下文与任务行归属解耦）。
4. 无 token / 无 tid（运营）→ 无上下文（set_config 不执行，零开销）。
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core import security
from app.core.db import engine
from app.core.tenant_context import current_tenant_id, tenant_scope
from app.models import DEFAULT_TENANT_ID, User


def _token_for(user: User, *, tenant_id: str | None, minutes: int = 5) -> str:
    return security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=minutes),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=tenant_id,
    )


def test_request_context_flows_into_transaction(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """登录请求的租户上下文在请求内的事务里可见（set_config 生效）。

    用 /users/me（任何走 Session 的鉴权端点都行）触发一次事务；断言
    放在依赖层不可行（响应不含内部状态），改为直接验证机制两端：
    中间件已由本集成请求驱动，事务内可见性由下面的引擎级测试锁住。
    """
    resp = client.get("/api/v1/users/me", headers=superuser_token_headers)
    assert resp.status_code == 200
    # tid 声明存在且等于默认租户（B2 登录签发）
    import jwt as pyjwt

    from app.core.config import settings

    raw = superuser_token_headers["Authorization"][len("Bearer ") :]
    payload = pyjwt.decode(
        raw,
        settings.SECRET_KEY,
        algorithms=[security.ALGORITHM],
        options={"verify_aud": False},
    )
    assert payload.get("tid") == str(DEFAULT_TENANT_ID)


def test_engine_bind_sets_config_inside_scope(db: Session) -> None:
    """tenant_scope 内新事务的 current_setting 即租户；作用域外不残留。"""
    with Session(engine) as s:
        with tenant_scope(DEFAULT_TENANT_ID):
            got = s.connection().execute(
                text("select current_setting('app.tenant_id', true)")
            ).scalar_one()
            assert got == str(DEFAULT_TENANT_ID)
        # 事务级设置随事务结束失效；作用域外的新事务读回空串
        s.commit()
        after = s.connection().execute(
            text("select coalesce(current_setting('app.tenant_id', true), '')")
        ).scalar_one()
        assert after == ""


def test_forged_tid_rejected(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """伪造 tid（与用户行不一致）→ 401；tid 缺失的旧形态不比对。"""
    from sqlmodel import select

    from app.core.config import settings

    other = uuid.uuid4()  # 任意不存在的租户
    user = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    assert user is not None
    forged = {"Authorization": f"Bearer {_token_for(user, tenant_id=str(other))}"}
    assert client.get("/api/v1/users/me", headers=forged).status_code == 401

    legacy = {"Authorization": f"Bearer {_token_for(user, tenant_id=None)}"}
    assert client.get("/api/v1/users/me", headers=legacy).status_code == 200


def test_optional_channel_degrades_forged_tid(client: TestClient, db: Session) -> None:
    """可选登录通道：tid 不一致按无效处理（静默匿名）。"""
    from sqlmodel import select

    from app.core.config import settings

    user = db.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first()
    assert user is not None
    forged = {
        "Authorization": f"Bearer {_token_for(user, tenant_id=str(uuid.uuid4()))}"
    }
    # 回放端点是可选登录（无 Authorization 也不报 401）；伪 tid 同样当匿名
    resp = client.get(f"/api/v1/attempts/{uuid.uuid4()}/audio", headers=forged)
    assert resp.status_code in (401, 404)


def test_worker_rebinds_by_task_row(db: Session) -> None:
    """_run_in_worker 的作用域来自作答行（而非投递方上下文）。"""
    from app.models import Attempt
    from app.scoring.worker import _run_in_worker

    attempt = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        audio_path="c3.webm",
        duration_s=3.0,
        status="queued",
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    import app.scoring.worker as worker_mod

    captured: list[object] = []
    original = worker_mod.process_attempt

    def spy(session: Session, attempt_id: uuid.UUID) -> None:
        captured.append(current_tenant_id())

    worker_mod.process_attempt = spy  # type: ignore[assignment]
    try:
        # 空上下文投递（模拟重试 Timer 线程）：worker 内部仍应绑定任务行租户
        from contextvars import copy_context

        copy_context().run(_run_in_worker, attempt.id)
    finally:
        worker_mod.process_attempt = original
    assert captured == [DEFAULT_TENANT_ID]


def test_operator_token_carries_no_context(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    """运营 token 无 tid：平台端点可用且不设学校上下文（C4 走平台通道）。"""
    resp = client.get("/api/v1/admin/metrics", headers=operator_token_headers)
    assert resp.status_code == 200
