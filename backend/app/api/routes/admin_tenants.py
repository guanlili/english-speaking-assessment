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
from app.models import (
    DEFAULT_TENANT_ID,
    MODULE_KEYS,
    Tenant,
    TenantModuleAuditPublic,
    TenantModulePublic,
    TenantModuleUpdate,
    User,
)
from app.services import entitlement

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
    """运营视角的学校行：基础字段 + 账号数 + 已配置模块清单。"""

    id: uuid.UUID
    slug: str
    name_zh: str
    name_en: str | None
    status: str
    timezone: str
    created_at: Any | None = None
    user_count: int = 0
    modules: list[TenantModulePublic] = []


def _module_rows(
    session: SASession, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TenantModulePublic]]:
    if not tenant_ids:
        return {}
    from app.models import TenantModule

    db_rows = session.exec(
        select(TenantModule).where(
            col(TenantModule.tenant_id).in_(tenant_ids)  # type: ignore[union-attr]
        )
    ).all()
    by_tenant: dict[uuid.UUID, list[TenantModulePublic]] = {
        tid: [] for tid in tenant_ids
    }
    for row in db_rows:
        by_tenant.setdefault(row.tenant_id, []).append(
            entitlement.public_module(row, row.tenant_id)
        )
    return by_tenant


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
    modules_by_tenant = _module_rows(session, [r.id for r in rows])
    return [
        TenantAdminPublic(
            **r.model_dump(),
            user_count=counts.get(r.id, 0),
            modules=modules_by_tenant.get(r.id, []),
        )
        for r in rows
    ]


@router.get("", response_model=list[TenantAdminPublic])
def list_tenants(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=200),
    expiring_within_days: int | None = Query(default=None, ge=1, le=365),
) -> Any:
    rows = list(
        session.exec(
            paged(select(Tenant).order_by(col(Tenant.created_at)), offset, limit)
        ).all()
    )
    if expiring_within_days is not None:
        expiring = entitlement.tenants_expiring_within(session, expiring_within_days)
        rows = [r for r in rows if r.id in expiring]
    return _with_counts(session, rows)


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


def _get_tenant_or_404(session: SASession, tenant_id: uuid.UUID) -> Tenant:
    row = session.get(Tenant, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    return row


@router.put("/{tenant_id}/modules/{module_key}", response_model=TenantModulePublic)
def update_tenant_module(
    session: PlatformSessionDep,
    operator: PlatformOperatorDep,
    tenant_id: uuid.UUID,
    module_key: str,
    body: TenantModuleUpdate,
) -> Any:
    """整校模块开关（平台运营）：开启/关闭 speaking 或 vocabulary，可选租期。

    请求体为 PUT 整行语义：省略的元数据字段保留旧值；``expires_at`` 显式传
    ``null`` 表示清除到期日（转长期）。``effective_at`` 即开始时间。
    变更落 ``tenant_module_audit``：操作人、前后值（含到期日/类型/授权人）、
    时间戳一并留痕；学校管理员不可见、不可改本接口。
    """
    _get_tenant_or_404(session, tenant_id)
    if module_key not in MODULE_KEYS:
        raise HTTPException(status_code=422, detail=f"模块无效：{module_key}")
    fields_set = body.model_fields_set
    row, _audit = entitlement.upsert_module(
        session,
        tenant_id=tenant_id,
        module_key=module_key,
        enabled=body.enabled,
        operator=operator,
        effective_at=body.effective_at,
        effective_at_set="effective_at" in fields_set,
        expires_at=body.expires_at,
        expires_at_set="expires_at" in fields_set,
        grant_type=body.grant_type,
        grant_type_set="grant_type" in fields_set,
    )
    return entitlement.public_module(row, row.tenant_id)


@router.get(
    "/{tenant_id}/modules/audit",
    response_model=list[TenantModuleAuditPublic],
)
def list_tenant_module_audit(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    tenant_id: uuid.UUID,
    module_key: str | None = Query(default=None),
) -> Any:
    """按学校查模块授权变更历史（可再按模块过滤），最新在前。"""
    _get_tenant_or_404(session, tenant_id)
    if module_key is not None and module_key not in MODULE_KEYS:
        raise HTTPException(status_code=422, detail=f"模块无效：{module_key}")
    rows = entitlement.list_audit(session, tenant_id, module_key)
    return [TenantModuleAuditPublic.model_validate(row) for row in rows]


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
