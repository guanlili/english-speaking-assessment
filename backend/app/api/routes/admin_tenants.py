"""多租户 D2：平台运营的学校管理（开校/停用/改名）.

设计依据 docs/multi-tenant-design.md §3.2/§4.1（D 期学校运营第一块面）：
开校此前只能 SSH 跑 onboard_tenant.sh——本路由把它搬进运营界面。
- 停用优先于删除：学校及其全部数据永不物理删除（FK 链与审计留存）；
  停用即挡新登录（入口 404 + 认证失败），存量 token 随过期自然失效。
- 默认学校（租户锚点）不允许停用/改名状态变更——停了会锁死主校。
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session as SASession
from sqlmodel import SQLModel, col, func, select

from app.api.deps import PlatformOperatorDep, PlatformSessionDep
from app.api.pagination import paged
from app.models import DEFAULT_TENANT_ID, Tenant, User

router = APIRouter(prefix="/admin/tenants", tags=["admin"])

VALID_TENANT_STATUSES = ("active", "paused")


class TenantCreate(SQLModel):
    slug: str = Query(pattern=r"^[a-z0-9][a-z0-9-]{1,30}$", max_length=32)
    name_zh: str = Query(min_length=1, max_length=120)
    name_en: str | None = Query(default=None, max_length=120)


class TenantUpdate(SQLModel):
    name_zh: str | None = Query(default=None, min_length=1, max_length=120)
    name_en: str | None = Query(default=None, max_length=120)
    status: str | None = Query(default=None, max_length=16)


class TenantAdminPublic(SQLModel):
    """运营视角的学校行：基础字段 + 账号数（排空校/核对开通）。"""

    id: uuid.UUID
    slug: str
    name_zh: str
    name_en: str | None
    status: str
    timezone: str
    created_at: Any | None = None
    user_count: int = 0


def _with_counts(session: SASession, rows: list[Tenant]) -> list[TenantAdminPublic]:
    if not rows:
        return []
    counts = dict(
        session.exec(
            select(User.tenant_id, func.count())
            .where(col(User.tenant_id).in_([r.id for r in rows]))  # type: ignore[operator]
            .group_by(col(User.tenant_id))
        ).all()
    )
    return [
        TenantAdminPublic(
            **r.model_dump(),
            user_count=counts.get(r.id, 0),
        )
        for r in rows
    ]


@router.get("", response_model=list[TenantAdminPublic])
def list_tenants(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> Any:
    rows = session.exec(
        paged(select(Tenant).order_by(col(Tenant.created_at)), offset, limit)
    ).all()
    return _with_counts(session, list(rows))


@router.post("", response_model=TenantAdminPublic)
def create_tenant(
    session: PlatformSessionDep, _operator: PlatformOperatorDep, tenant_in: TenantCreate
) -> Any:
    slug = tenant_in.slug.strip().lower()
    if session.exec(select(Tenant).where(Tenant.slug == slug)).first() is not None:
        raise HTTPException(status_code=409, detail="学校码已存在")
    row = Tenant(slug=slug, name_zh=tenant_in.name_zh, name_en=tenant_in.name_en)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _with_counts(session, [row])[0]


@router.patch("/{tenant_id}", response_model=TenantAdminPublic)
def update_tenant(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    tenant_id: uuid.UUID,
    tenant_in: TenantUpdate,
) -> Any:
    row = session.get(Tenant, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    update = tenant_in.model_dump(exclude_unset=True)
    if "status" in update:
        if update["status"] not in VALID_TENANT_STATUSES:
            raise HTTPException(status_code=422, detail="状态无效（active/paused）")
        if row.id == DEFAULT_TENANT_ID and update["status"] != row.status:
            # 默认学校是租户锚点：停用会锁死主校与种子链路
            raise HTTPException(status_code=422, detail="默认学校不允许停用")
    row.sqlmodel_update(update)
    session.add(row)
    session.commit()
    session.refresh(row)
    return _with_counts(session, [row])[0]
