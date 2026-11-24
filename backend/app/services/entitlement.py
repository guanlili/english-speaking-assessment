"""模块授权域逻辑（#516 / #517：整校 × 模块开关 + 租期/试用状态机）。

口径：
- 可售模块只有 ``speaking`` / ``vocabulary``；PK、农场、FSRS 复习是
  vocabulary 的子能力，不单独开关。
- 授权粒度 = 整校一行；缺行 = 未购买（默认关闭），无班级 override、
  无白名单、无按班灰度。
- ``effective_at`` 即开始时间：空 = 立即生效；未来时间点尚未生效。不另设
  重复的 starts_at 列，API 响应里的 ``starts_at`` 只是它的只读镜像。
- ``expires_at`` 空 = 长期；now >= expires_at 即到期（expired）。到期只关门禁，
  绝不物理删除业务作答/任务数据。
- 403 detail 用稳定标识：未购/关闭/待生效 → ``module_not_enabled:<key>``；
  已到期 → ``module_expired:<key>``。401 只留给 token 无效/过期。

状态优先级（高 → 低）::

    not_granted（缺行）
      └─ disabled（enabled=false；即使同时过期也优先报 disabled）
           └─ scheduled（已开但开始时间在未来）
                └─ expired（已过到期日）
                     └─ active（其余）
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    GRANT_MANUAL,
    GRANT_TRIAL,
    GRANT_TYPES,
    MODULE_KEYS,
    PlatformOperator,
    TenantModule,
    TenantModuleAudit,
    TenantModulePublic,
)

# ── 状态常量（门禁、/modules/me、运营筛选共用同一口径）─────────────────────
STATE_NOT_GRANTED = "not_granted"
STATE_DISABLED = "disabled"
STATE_SCHEDULED = "scheduled"
STATE_EXPIRED = "expired"
STATE_ACTIVE = "active"

_DAY_SECONDS = 86400


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# ── 纯状态计算（不碰会话，便于复用与测试）─────────────────────────────────


def compute_state(row: TenantModule | None, now: datetime) -> str:
    """单行授权的派生状态；缺行 = not_granted。

    判定顺序固定：``enabled=false`` 优先于过期——关闭与过期同时成立时报
    ``disabled``，不被 expired 覆盖。
    """
    if row is None:
        return STATE_NOT_GRANTED
    if not row.enabled:
        return STATE_DISABLED
    if row.effective_at is not None and _as_utc(row.effective_at) > now:
        return STATE_SCHEDULED
    if row.expires_at is not None and _as_utc(row.expires_at) <= now:
        # 到点即过期：now >= expires_at 即 expired，不留宽限（宽限属于商务策略，
        # 不在代码里硬编码）。
        return STATE_EXPIRED
    return STATE_ACTIVE


def compute_days_left(row: TenantModule | None, now: datetime) -> int | None:
    """距到期日的剩余整天数（24h 块向上取整）；长期/缺行返回 None。

    已到期返回 0，不返回负数。示例：剩 1 天 2 小时 → 2 天；剩 2 小时 → 1 天。
    """
    if row is None or row.expires_at is None:
        return None
    remaining = _as_utc(row.expires_at) - now
    if remaining.total_seconds() <= 0:
        return 0
    return math.ceil(remaining.total_seconds() / _DAY_SECONDS)


def get_module_row(
    session: Session, tenant_id: uuid.UUID, module_key: str
) -> TenantModule | None:
    return session.exec(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,  # type: ignore[arg-type]
            TenantModule.module_key == module_key,  # type: ignore[arg-type]
        )
    ).first()


def module_status(session: Session, tenant_id: uuid.UUID, module_key: str) -> dict:
    """单行（含缺行）的对外状态快照，门禁、/modules/me、运营视角同口径。"""
    row = get_module_row(session, tenant_id, module_key)
    now = _now()
    return {
        "module_key": module_key,
        "enabled": row.enabled if row is not None else False,
        "effective_at": row.effective_at if row is not None else None,
        # starts_at 是 effective_at 的只读镜像，同一事实，不另存列。
        "starts_at": row.effective_at if row is not None else None,
        "expires_at": row.expires_at if row is not None else None,
        "grant_type": row.grant_type if row is not None else GRANT_MANUAL,
        "granted_by": row.granted_by if row is not None else None,
        "state": compute_state(row, now),
        "days_left": compute_days_left(row, now),
    }


def public_module(row: TenantModule | None, tenant_id: uuid.UUID) -> TenantModulePublic:
    """组装运营/前端视角的单行授权响应（含派生 state、days_left）。"""
    now = _now()
    return TenantModulePublic(
        tenant_id=tenant_id,
        module_key=row.module_key if row is not None else "",
        enabled=row.enabled if row is not None else False,
        effective_at=row.effective_at if row is not None else None,
        starts_at=row.effective_at if row is not None else None,
        expires_at=row.expires_at if row is not None else None,
        grant_type=row.grant_type if row is not None else GRANT_MANUAL,
        granted_by=row.granted_by if row is not None else None,
        state=compute_state(row, now),
        days_left=compute_days_left(row, now),
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
    )


def list_statuses(session: Session, tenant_id: uuid.UUID) -> list[dict]:
    """两个可售模块的状态快照；缺行也返回 not_granted 行，不 404。"""
    return [module_status(session, tenant_id, key) for key in MODULE_KEYS]


def list_enabled_modules(session: Session, tenant_id: uuid.UUID) -> list[str]:
    """当前活跃（active）的模块 key 清单；其余状态均不计入。"""
    rows = session.exec(
        select(TenantModule).where(TenantModule.tenant_id == tenant_id)  # type: ignore[arg-type]
    ).all()
    now = _now()
    return [row.module_key for row in rows if compute_state(row, now) == STATE_ACTIVE]


def is_module_enabled(session: Session, tenant_id: uuid.UUID, module_key: str) -> bool:
    row = get_module_row(session, tenant_id, module_key)
    return compute_state(row, _now()) == STATE_ACTIVE


def ensure_module_enabled(
    session: Session, tenant_id: uuid.UUID, module_key: str
) -> None:
    """模块闸门：按状态机判定，403 detail 区分未购与到期。

    判定顺序：
    1. 非法 key → 500（配置错误，不是业务拒绝）；
    2. not_granted / disabled / scheduled → 403 ``module_not_enabled:<key>``；
    3. expired → 403 ``module_expired:<key>``；
    4. active 放行。

    只认整校口径，不读班级、不做名单判断；班级成员 404 由各端点在
    成员解析阶段先行抛出（404 优先于模块 403）。401 不用于模块口径。
    """
    if module_key not in MODULE_KEYS:
        raise HTTPException(status_code=500, detail=f"unknown module: {module_key}")
    row = get_module_row(session, tenant_id, module_key)
    state = compute_state(row, _now())
    if state == STATE_EXPIRED:
        raise HTTPException(status_code=403, detail=f"module_expired:{module_key}")
    if state != STATE_ACTIVE:
        raise HTTPException(status_code=403, detail=f"module_not_enabled:{module_key}")


# ── 运营改写 + 审计 ──────────────────────────────────────────────────────


def _audit_action(enabled: bool) -> str:
    return "grant" if enabled else "revoke"


def _validate_grant(
    *,
    grant_type: str | None,
    expires_at: datetime | None,
    effective_at: datetime | None,
) -> None:
    """请求级校验：类型枚举、trial 必带到期日、到期日晚于开始时间。

    ``effective_at`` 为空（立即生效）时不做先后校验：过去的 ``expires_at``
    允许写入，状态直接判 ``expired``；只有显式给出开始时间时，才要求
    ``expires_at > effective_at``。
    """
    if grant_type not in GRANT_TYPES:
        raise HTTPException(status_code=422, detail="grant_type_invalid")
    if grant_type == GRANT_TRIAL and expires_at is None:
        raise HTTPException(status_code=422, detail="trial_requires_expires_at")
    if expires_at is not None and effective_at is not None:
        if _as_utc(expires_at) <= _as_utc(effective_at):
            raise HTTPException(
                status_code=422,
                detail="expires_at_must_be_after_effective_at",
            )


def upsert_module(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    module_key: str,
    enabled: bool,
    operator: PlatformOperator | None,
    effective_at: datetime | None,
    effective_at_set: bool,
    expires_at: datetime | None,
    expires_at_set: bool,
    grant_type: str | None,
    grant_type_set: bool,
) -> tuple[TenantModule, TenantModuleAudit]:
    """运营通道改写单行授权，并落一条审计。幂等：状态未变也留痕。

    省略的元数据字段保留旧值（``*_set`` 标识请求体是否显式给出）；
    ``expires_at`` 显式传 null = 清除到期日（转长期）。
    """
    if module_key not in MODULE_KEYS:
        raise HTTPException(status_code=422, detail=f"模块无效：{module_key}")

    row = get_module_row(session, tenant_id, module_key)
    existed = row is not None

    # 解析新值：省略 → 保留旧值；新行缺省 manual / 长期 / 立即生效。
    new_effective = (
        effective_at if effective_at_set else (row.effective_at if existed else None)
    )
    new_expires = (
        expires_at if expires_at_set else (row.expires_at if existed else None)
    )
    resolved_grant_type: str | None = (
        grant_type if grant_type_set else (row.grant_type if existed else GRANT_MANUAL)
    )

    now = _now()
    _validate_grant(
        grant_type=resolved_grant_type,
        expires_at=new_expires,
        effective_at=new_effective,
    )
    # 校验通过后 None 不可能落到这里（None 不在枚举内会被 422 拒绝）
    new_grant_type = resolved_grant_type or GRANT_MANUAL

    enabled_before = row.enabled if existed else None
    effective_before = row.effective_at if existed else None
    expires_before = row.expires_at if existed else None
    grant_type_before = row.grant_type if existed else None
    granted_by_before = row.granted_by if existed else None

    operator_id = operator.id if operator is not None else None

    # granted_by 归属规则：首次开通 / 从关闭变开启 / 续期或改类型 → 记当前
    # 操作人；单纯关闭或未变更授权归属时保留旧值。updated_by 仍是最后改动者。
    if not existed:
        new_granted_by = operator_id
    elif (not row.enabled) and enabled:
        new_granted_by = operator_id
    elif new_expires != expires_before or new_grant_type != grant_type_before:
        new_granted_by = operator_id
    else:
        new_granted_by = row.granted_by

    if row is None:
        row = TenantModule(tenant_id=tenant_id, module_key=module_key)
    row.enabled = enabled
    row.effective_at = new_effective
    row.expires_at = new_expires
    row.grant_type = new_grant_type
    row.granted_by = new_granted_by
    row.updated_by = operator_id
    row.updated_at = now
    session.add(row)

    audit = TenantModuleAudit(
        tenant_id=tenant_id,
        module_key=module_key,
        action=_audit_action(enabled),
        enabled_before=enabled_before,
        enabled_after=enabled,
        effective_at_before=effective_before,
        effective_at_after=new_effective,
        expires_at_before=expires_before,
        expires_at_after=new_expires,
        grant_type_before=grant_type_before,
        grant_type_after=new_grant_type,
        granted_by_before=granted_by_before,
        granted_by_after=new_granted_by,
        actor_operator_id=operator_id,
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


def tenants_expiring_within(
    session: Session, days: int, now: datetime | None = None
) -> set[uuid.UUID]:
    """命中「N 天内到期」的学校 id 集合。

    条件：存在 ``enabled=true``、``expires_at`` 非空、
    ``now <= expires_at <= now + N 天`` 的模块行。已过期（expires_at < now）
    不计入本筛选；长期（null）不计入。
    """
    now = now or _now()
    deadline = now + timedelta(days=days)
    rows = session.exec(
        select(TenantModule.tenant_id).where(
            col(TenantModule.enabled).is_(True),  # type: ignore[union-attr]
            col(TenantModule.expires_at).is_not(None),  # type: ignore[union-attr]
            col(TenantModule.expires_at) > now,  # type: ignore[operator]
            col(TenantModule.expires_at) <= deadline,  # type: ignore[operator]
        )
    ).all()
    return set(rows)
