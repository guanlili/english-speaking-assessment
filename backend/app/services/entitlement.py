"""模块授权域逻辑（#516 / #517：整校 × 模块开关）。

口径：
- 可售模块只有 ``speaking`` / ``vocabulary``；PK、农场、FSRS 复习是
  vocabulary 的子能力，不单独开关。
- 授权粒度 = 整校一行；缺行 = 未购买（默认关闭），无班级 override、
  无白名单、无按班灰度。
- ``effective_at`` 为空 = 立即生效；未来时间点尚未生效，按未购买处理。
- 403 detail 用稳定标识 ``module_not_enabled:<key>``，前端按标识映射双语；
  401 只留给 token 无效/过期，模块未购不触发登出。
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    MODULE_KEYS,
    PlatformOperator,
    TenantModule,
    TenantModuleAudit,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _row_active(row: TenantModule, now: datetime) -> bool:
    if not row.enabled:
        return False
    if row.effective_at is not None and _as_utc(row.effective_at) > now:
        return False
    return True


def get_module_row(
    session: Session, tenant_id: uuid.UUID, module_key: str
) -> TenantModule | None:
    return session.exec(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,  # type: ignore[arg-type]
            TenantModule.module_key == module_key,  # type: ignore[arg-type]
        )
    ).first()


def list_enabled_modules(session: Session, tenant_id: uuid.UUID) -> list[str]:
    """当前已生效的模块 key 清单（缺行/关闭/未到生效时间均不计入）。"""
    rows = session.exec(
        select(TenantModule).where(TenantModule.tenant_id == tenant_id)  # type: ignore[arg-type]
    ).all()
    now = _now()
    return [row.module_key for row in rows if _row_active(row, now)]


def is_module_enabled(session: Session, tenant_id: uuid.UUID, module_key: str) -> bool:
    row = get_module_row(session, tenant_id, module_key)
    return row is not None and _row_active(row, _now())


def ensure_module_enabled(
    session: Session, tenant_id: uuid.UUID, module_key: str
) -> None:
    """模块闸门：未购/未生效 → 403 ``module_not_enabled:<key>``。

    只认整校口径，不读班级、不做名单判断；班级成员 404 由各端点在
    成员解析阶段先行抛出（404 优先于模块 403）。
    """
    if module_key not in MODULE_KEYS:
        raise HTTPException(status_code=500, detail=f"unknown module: {module_key}")
    if not is_module_enabled(session, tenant_id, module_key):
        raise HTTPException(status_code=403, detail=f"module_not_enabled:{module_key}")


def _audit_action(enabled: bool, existed: bool) -> str:
    if not existed:
        return "grant" if enabled else "revoke"
    return "grant" if enabled else "revoke"


def upsert_module(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    module_key: str,
    enabled: bool,
    operator: PlatformOperator | None,
    effective_at: datetime | None,
) -> tuple[TenantModule, TenantModuleAudit]:
    """运营通道改写单行授权，并落一条审计。幂等：状态未变也留痕。"""
    if module_key not in MODULE_KEYS:
        raise HTTPException(status_code=422, detail=f"模块无效：{module_key}")

    row = get_module_row(session, tenant_id, module_key)
    existed = row is not None
    enabled_before = row.enabled if existed else None
    effective_before = row.effective_at if existed else None

    if row is None:
        row = TenantModule(tenant_id=tenant_id, module_key=module_key)
    row.enabled = enabled
    row.effective_at = effective_at
    row.updated_by = operator.id if operator is not None else None
    row.updated_at = _now()
    session.add(row)

    audit = TenantModuleAudit(
        tenant_id=tenant_id,
        module_key=module_key,
        action=_audit_action(enabled, existed),
        enabled_before=enabled_before,
        enabled_after=enabled,
        effective_at_before=effective_before,
        effective_at_after=effective_at,
        actor_operator_id=operator.id if operator is not None else None,
    )
    session.add(audit)
    session.commit()
    session.refresh(row)
    session.refresh(audit)
    return row, audit


def list_audit(
    session: Session, tenant_id: uuid.UUID, module_key: str | None = None
) -> list[TenantModuleAudit]:
    stmt = select(TenantModuleAudit).where(
        TenantModuleAudit.tenant_id == tenant_id  # type: ignore[arg-type]
    )
    if module_key is not None:
        stmt = stmt.where(TenantModuleAudit.module_key == module_key)  # type: ignore[arg-type]
    stmt = stmt.order_by(
        col(TenantModuleAudit.created_at).desc(),
        col(TenantModuleAudit.id).desc(),
    )
    return list(session.exec(stmt).all())
