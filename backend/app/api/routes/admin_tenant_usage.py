"""平台运营：按租户按天的用量聚合（#517 B 部分）。

与 ``admin_tenants.py`` 的学校清单逻辑解耦：本文件只挂用量只读端点，鉴权走
平台运营独立身份（``PlatformSessionDep + PlatformOperatorDep``）。

口径与限制见 ``app/services/tenant_usage.py`` 与 ``docs/tenant-usage-metrics.md``：
只出聚合数，不返回学生 / 教师标识；登录活跃与逐日农场收获两个缺口在
``limitations`` 明示。
"""

import csv
import io
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field
from sqlmodel import Session as SASession
from sqlmodel import SQLModel, col, select

from app.api.deps import PlatformOperatorDep, PlatformSessionDep
from app.models import Tenant
from app.services import tenant_usage
from app.services.tenant_usage import LIMITATIONS, METRIC_KEYS

router = APIRouter(prefix="/admin/tenants", tags=["admin"])

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30


class TenantUsageMetrics(SQLModel):
    """九项聚合指标（日行与区间总量共用结构）。"""

    active_teachers: int = 0
    active_students: int = 0
    vocab_answers: int = 0
    published_tasks: int = 0
    completed_students: int = 0
    pk_matches: int = 0
    farm_harvests: int = 0
    placement_tests: int = 0
    exports: int = 0


class TenantUsageDay(TenantUsageMetrics):
    date: str


class TenantUsageResponse(SQLModel):
    tenant_id: uuid.UUID
    date_from: str = Field(alias="from")
    date_to: str = Field(alias="to")
    timezone: str
    days: list[TenantUsageDay]
    totals: TenantUsageMetrics
    limitations: list[str]


class TenantUsageSummaryItem(SQLModel):
    tenant_id: uuid.UUID
    slug: str
    summary_7d: TenantUsageMetrics
    summary_30d: TenantUsageMetrics


class TenantUsageSummaryResponse(SQLModel):
    items: list[TenantUsageSummaryItem]


def _get_tenant_or_404(session: SASession, tenant_id: uuid.UUID) -> Tenant:
    row = session.get(Tenant, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    return row


def _resolve_range(
    tenant: Tenant,
    from_q: date | None,
    to_q: date | None,
) -> tuple[date, date]:
    """解析缺省日期与范围校验；日界按租户时区，非法范围 422。"""
    today = tenant_usage.today_in_tz(tenant.timezone)
    to_date = to_q or today
    from_date = from_q or (to_date - timedelta(days=DEFAULT_RANGE_DAYS - 1))
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="起始日期不能晚于结束日期")
    if (to_date - from_date).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422, detail=f"查询范围不能超过 {MAX_RANGE_DAYS} 天"
        )
    return from_date, to_date


def _usage_payload(
    session: SASession, tenant: Tenant, from_date: date, to_date: date
) -> dict[str, Any]:
    days = tenant_usage.tenant_usage_daily(
        session,
        tenant_id=tenant.id,
        from_date=from_date,
        to_date=to_date,
        timezone=tenant.timezone,
    )
    totals = tenant_usage.tenant_usage_totals(days)
    return {
        "tenant_id": tenant.id,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "timezone": tenant.timezone,
        "days": days,
        "totals": totals,
        "limitations": list(LIMITATIONS),
    }


@router.get("/usage-summary", response_model=TenantUsageSummaryResponse)
def usage_summary(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
) -> Any:
    """运营列表：每校近 7 / 30 天核心聚合数（一次请求返回两组）。

    只返回租户 id、slug 与聚合数，不含任何学生 / 教师标识。静态路径
    ``usage-summary`` 与 ``/{tenant_id}`` 不冲突。
    """
    tenants = session.exec(select(Tenant).order_by(col(Tenant.created_at))).all()
    items: list[TenantUsageSummaryItem] = []
    for tenant in tenants:
        summary = tenant_usage.tenant_usage_summary(session, tenant)
        items.append(
            TenantUsageSummaryItem(
                tenant_id=tenant.id,
                slug=tenant.slug,
                summary_7d=TenantUsageMetrics(**summary[7]),
                summary_30d=TenantUsageMetrics(**summary[30]),
            )
        )
    return {"items": items}


@router.get("/{tenant_id}/usage", response_model=TenantUsageResponse)
def tenant_usage_detail(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    tenant_id: uuid.UUID,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
) -> Any:
    """单校按天用量：范围内每天一行（无数据补零），附区间总量与限制说明。"""
    tenant = _get_tenant_or_404(session, tenant_id)
    from_date, to_date = _resolve_range(tenant, from_, to)
    return _usage_payload(session, tenant, from_date, to_date)


_CSV_HEADERS = (
    "日期",
    "活跃教师数",
    "活跃学生数",
    "词汇作答数",
    "发布任务数",
    "完成任务人数",
    "PK 对局数",
    "农场收获数（下限）",
    "placement 测试数",
    "导出次数",
)


@router.get("/{tenant_id}/usage.csv")
def tenant_usage_csv(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    tenant_id: uuid.UUID,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
) -> Response:
    """单校按天用量 CSV（UTF-8 BOM，Excel 直开）；仅聚合数，无学生明细。"""
    tenant = _get_tenant_or_404(session, tenant_id)
    from_date, to_date = _resolve_range(tenant, from_, to)
    payload = _usage_payload(session, tenant, from_date, to_date)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADERS)
    for row in payload["days"]:
        writer.writerow([row["date"], *[row[key] for key in METRIC_KEYS]])

    filename = (
        f"tenant-{tenant.slug}-usage-{from_date.isoformat()}-{to_date.isoformat()}.csv"
    )
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
