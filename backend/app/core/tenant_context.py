"""TenantSession：多租户租户上下文与事务级数据库绑定（B1 转正自原型）.

原型验证结论（docs/multi-tenant-a-inventory.md §3，12/12 通过）：
- `set_config('app.tenant_id', :t, true)` 是事务级——commit 后即失效，
  因此必须在**每一次新事务开始**时重绑，不能只在请求入口设一次；
- 引擎级 `begin` 事件 + ContextVar 是覆盖 Session 与裸
  `connection().execute` 两类路径的最小机制；
- 未设上下文时不执行 set_config——配合 RLS 策略
  `coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text`
  即「缺上下文默认拒绝」。

B1 阶段本模块仅落地机制与单测，**尚未接入 deps.get_db、也未在业务表启用
RLS**——接入时机在 C 期收紧（设计稿 §9-5），避免半接入状态下业务查询被
默认拒绝策略拦死。新代码（B2+ 登录租户解析、平台运营通道）应优先使用
本模块建立上下文。
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import sqlalchemy.event
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

_TENANT_CTX: ContextVar[uuid.UUID | None] = ContextVar("tenant_id", default=None)


def current_tenant_id() -> uuid.UUID | None:
    """当前协程/线程绑定的租户；未绑定为 None（RLS 下即默认拒绝）。"""
    return _TENANT_CTX.get()


@contextmanager
def tenant_scope(tenant_id: uuid.UUID) -> Iterator[uuid.UUID]:
    """在 with 块内绑定租户：新事务自动 set_config，块外自动解绑。

    用法（HTTP 依赖与后台任务共用同一形态）：
        with tenant_scope(user.tenant_id):
            with Session(engine) as session: ...
    """
    token = _TENANT_CTX.set(tenant_id)
    try:
        yield tenant_id
    finally:
        _TENANT_CTX.reset(token)


def install_tenant_bind(engine) -> None:
    """给引擎装上「每次事务开始重绑租户」的事件（幂等，可对多引擎调用）。

    必须在引擎被业务使用前安装；事务内未绑租户则不执行 set_config
    （配合 RLS 默认拒绝，见模块 docstring）。
    """
    if getattr(engine, "_belp_tenant_bind_installed", False):
        return
    engine._belp_tenant_bind_installed = True  # type: ignore[attr-defined]

    @sqlalchemy.event.listens_for(engine, "begin")
    def _bind_tenant(conn) -> None:  # pragma: no cover - 由 test_tenant_session 驱动
        tid = _TENANT_CTX.get()
        if tid is not None:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tid)}
            )


def tenant_session_factory(engine) -> sessionmaker:
    """返回绑定租户事件的 sessionmaker（TenantSession 工厂入口）。"""
    install_tenant_bind(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
