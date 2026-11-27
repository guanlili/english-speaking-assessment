"""按租户按天的用量聚合（#517 B 部分）。

只出聚合数，**不返回任何学生 / 教师标识**（id、姓名、学号均不进 API）。

九项指标口径（逐条定义见 ``docs/tenant-usage-metrics.md``）：

=======================  ================================================================
字段                      定义
=======================  ================================================================
``active_teachers``       当天有教学操作的去重教师数：发布词汇任务 / 发布课堂练习 /
                          词条内容审核三类操作的操作人去重并集。
``active_students``       当天有词汇作答的去重学生数（经作答会话反查 student_id）。
``vocab_answers``        词汇作答条数（``vocabulary_answer`` 每行一次作答）。
``published_tasks``       当天发布的词汇任务数（``vocabulary_assignment``）。
``completed_students``    当天完成教师任务的去重学生数（``kind='task'`` 且
                          ``status='submitted'`` 的会话反查 student_id）。
``pk_matches``           当天开始的 PK 对局数（``vocab_pk_match``）。
``farm_harvests``        当天「最近一次收获落在该日」的地块数（**下限口径**，
                          不是当日真实收获次数——见限制说明）。
``placement_tests``       当天完成的 placement 粗分档测试数（``vocab_placement_result``）。
``exports``               当天创建的导出任务数（``export_audit`` 中 ``action='create'``）。
=======================  ================================================================

两个必须诚实披露的缺口（不得编数，已同步进 API ``limitations``）：

1. **登录活跃无法统计**：当前没有登录日志 / ``last_login_at``，不新增登录埋点、
   不改 User 表。因此活跃教师 = 当天有教学操作的去重教师，活跃学生 = 当天有
   词汇作答的去重学生，**不含仅登录未操作的账号**。
2. **农场无逐日收获事件**：``vocab_farm_plot`` 只有累计 ``harvest_count`` 与
   最近一次 ``last_harvested_at``，没有逐日收获事件表，无法回算当日真实收获
   次数。``farm_harvests`` 是「最近一次收获落在该日的账号数」的**下限**。

日界：按租户 ``Tenant.timezone``（默认 Asia/Shanghai）自然日切分；范围条件转
UTC 时间戳裁剪，分组时再按租户时区转回本地日期。返回的 ``date`` 是该租户本地日期。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, union_all
from sqlmodel import Session, col

from app.models import (
    ClassroomExercise,
    ExportAudit,
    Tenant,
    VocabFarmPlot,
    VocabPkMatch,
    VocabPlacementResult,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyContentReviewAudit,
    VocabularySession,
)

#: 九项指标字段名（对外固定，前端 / CSV / 汇总都按此顺序）
METRIC_KEYS: tuple[str, ...] = (
    "active_teachers",
    "active_students",
    "vocab_answers",
    "published_tasks",
    "completed_students",
    "pk_matches",
    "farm_harvests",
    "placement_tests",
    "exports",
)

#: 运营列表展示的核心五项（其余四项随总量附带）
CORE_METRIC_KEYS: tuple[str, ...] = (
    "active_teachers",
    "active_students",
    "vocab_answers",
    "published_tasks",
    "completed_students",
)

DEFAULT_TZ = "Asia/Shanghai"

#: 限制说明（稳定标识，前端按文案映射；措辞调整需同步前端分流）
LIMITATION_LOGIN = (
    "活跃口径不含仅登录用户：当前没有登录日志或 last_login_at，"
    "活跃教师=当天有教学操作（发布词汇任务/课堂练习/内容审核）的去重教师，"
    "活跃学生=当天有词汇作答的去重学生。"
)
LIMITATION_FARM = (
    "farm_harvests 为下限口径：农场只保存累计 harvest_count 与最近一次 "
    "last_harvested_at，没有逐日收获事件，无法回算当日真实收获次数；本数是"
    "「最近一次收获落在当日」的地块数。"
)
LIMITATIONS: tuple[str, ...] = (LIMITATION_LOGIN, LIMITATION_FARM)

_SESSION_KIND_TASK = "task"
_SESSION_STATUS_SUBMITTED = "submitted"
_EXPORT_ACTION_CREATE = "create"


def _zoneinfo(timezone: str) -> ZoneInfo:
    """租户时区解析；非法 / 缺失回退默认时区，不让聚合整体失败。"""
    try:
        return ZoneInfo(timezone or DEFAULT_TZ)
    except ZoneInfoNotFoundError, ValueError:
        return ZoneInfo(DEFAULT_TZ)


def today_in_tz(timezone: str) -> date:
    """租户时区下的当前本地日期（缺省区间的右端点）。"""
    return datetime.now(_zoneinfo(timezone)).date()


def _bounds(from_date: date, to_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """本地自然日区间转 UTC 半开区间 ``[start, end)``。"""
    start = datetime.combine(from_date, datetime.min.time(), tzinfo=tz).astimezone(UTC)
    end = datetime.combine(
        to_date + timedelta(days=1), datetime.min.time(), tzinfo=tz
    ).astimezone(UTC)
    return start, end


def _local_day(tz: str, time_col):
    """按租户时区把 timestamptz 截断为本地日期（PG ``timezone`` + ``date``）。"""
    return func.date(func.timezone(tz, time_col))


def _zero_metrics() -> dict[str, int]:
    return dict.fromkeys(METRIC_KEYS, 0)


def _count_by_day(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tz: str,
    start: datetime,
    end: datetime,
    model,
    time_col,
    distinct_col=None,
    extra_filters=(),
) -> dict[date, int]:
    """单表按本地日聚合：计数（可选去重），返回 ``{本地日期: 计数}``。"""
    day = _local_day(tz, time_col)
    count_col = (
        func.count(func.distinct(distinct_col))
        if distinct_col is not None
        else func.count()
    )
    stmt = (
        select(day.label("day"), count_col.label("cnt"))
        .where(
            col(model.tenant_id) == tenant_id,
            time_col >= start,
            time_col < end,
            *extra_filters,
        )
        .group_by(day)
    )
    rows = session.exec(stmt).all()
    return {row.day: (row.cnt or 0) for row in rows}


def _teacher_actor_union(tenant_id: uuid.UUID, tz: str, start: datetime, end: datetime):
    """三类教学操作的 (本地日, 操作人) 并集子查询。

    - 发布词汇任务：``vocabulary_assignment.created_by`` / ``published_at``
    - 发布课堂练习：``classroom_exercise.created_by`` / ``published_at``
    - 词条内容审核：``vocabulary_content_review_audit.actor_id`` / ``created_at``
    """
    assignment = select(
        _local_day(tz, VocabularyAssignment.published_at).label("day"),
        col(VocabularyAssignment.created_by).label("actor"),
    ).where(
        col(VocabularyAssignment.tenant_id) == tenant_id,
        col(VocabularyAssignment.published_at) >= start,  # type: ignore[union-attr]
        col(VocabularyAssignment.published_at) < end,  # type: ignore[union-attr]
        col(VocabularyAssignment.created_by).is_not(None),
    )
    exercise = select(
        _local_day(tz, ClassroomExercise.published_at).label("day"),
        col(ClassroomExercise.created_by).label("actor"),
    ).where(
        col(ClassroomExercise.tenant_id) == tenant_id,
        col(ClassroomExercise.published_at) >= start,  # type: ignore[union-attr]
        col(ClassroomExercise.published_at) < end,  # type: ignore[union-attr]
        col(ClassroomExercise.created_by).is_not(None),
    )
    review = select(
        _local_day(tz, VocabularyContentReviewAudit.created_at).label("day"),
        col(VocabularyContentReviewAudit.actor_id).label("actor"),
    ).where(
        col(VocabularyContentReviewAudit.tenant_id) == tenant_id,
        col(VocabularyContentReviewAudit.created_at) >= start,  # type: ignore[union-attr]
        col(VocabularyContentReviewAudit.created_at) < end,  # type: ignore[union-attr]
        col(VocabularyContentReviewAudit.actor_id).is_not(None),
    )
    return union_all(assignment, exercise, review)


def _teachers_by_day(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tz: str,
    start: datetime,
    end: datetime,
) -> dict[date, int]:
    """教学操作去重教师按日计数。"""
    union = _teacher_actor_union(tenant_id, tz, start, end).subquery()
    stmt = select(union.c.day, func.count(func.distinct(union.c.actor))).group_by(
        union.c.day
    )
    rows = session.connection().execute(stmt).all()
    return {row[0]: (row[1] or 0) for row in rows}


def _students_by_day(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tz: str,
    start: datetime,
    end: datetime,
) -> dict[date, int]:
    """有词汇作答的去重学生按日计数（作答经会话反查 student_id）。"""
    day = _local_day(tz, VocabularyAnswer.answered_at)
    stmt = (
        select(
            day.label("day"), func.count(func.distinct(VocabularySession.student_id))
        )
        .select_from(VocabularyAnswer)
        .join(
            VocabularySession,
            col(VocabularySession.id) == col(VocabularyAnswer.session_id),
        )
        .where(
            col(VocabularyAnswer.tenant_id) == tenant_id,
            col(VocabularyAnswer.answered_at) >= start,  # type: ignore[union-attr]
            col(VocabularyAnswer.answered_at) < end,  # type: ignore[union-attr]
        )
        .group_by(day)
    )
    rows = session.exec(stmt).all()
    return {row.day: (row[1] or 0) for row in rows}


def _collect_day_maps(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tz: str,
    start: datetime,
    end: datetime,
) -> dict[str, dict[date, int]]:
    """九项指标各自的 ``{本地日期: 计数}`` 映射；全部 SQL 聚合，不回拉明细行。"""
    maps: dict[str, dict[date, int]] = {key: {} for key in METRIC_KEYS}
    maps["active_teachers"] = _teachers_by_day(
        session, tenant_id=tenant_id, tz=tz, start=start, end=end
    )
    maps["active_students"] = _students_by_day(
        session, tenant_id=tenant_id, tz=tz, start=start, end=end
    )
    maps["vocab_answers"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=VocabularyAnswer,
        time_col=VocabularyAnswer.answered_at,
    )
    maps["published_tasks"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=VocabularyAssignment,
        time_col=VocabularyAssignment.published_at,
    )
    maps["completed_students"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=VocabularySession,
        time_col=VocabularySession.submitted_at,
        distinct_col=VocabularySession.student_id,
        extra_filters=(
            col(VocabularySession.kind) == _SESSION_KIND_TASK,
            col(VocabularySession.status) == _SESSION_STATUS_SUBMITTED,
            col(VocabularySession.submitted_at).is_not(None),
        ),
    )
    maps["pk_matches"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=VocabPkMatch,
        time_col=VocabPkMatch.started_at,
    )
    maps["farm_harvests"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=VocabFarmPlot,
        time_col=VocabFarmPlot.last_harvested_at,
        extra_filters=(col(VocabFarmPlot.last_harvested_at).is_not(None),),
    )
    maps["placement_tests"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=VocabPlacementResult,
        time_col=VocabPlacementResult.submitted_at,
    )
    maps["exports"] = _count_by_day(
        session,
        tenant_id=tenant_id,
        tz=tz,
        start=start,
        end=end,
        model=ExportAudit,
        time_col=ExportAudit.created_at,
        extra_filters=(col(ExportAudit.action) == _EXPORT_ACTION_CREATE,),
    )
    return maps


def tenant_usage_daily(
    session: Session,
    tenant_id: uuid.UUID,
    from_date: date,
    to_date: date,
    timezone: str,
) -> list[dict[str, object]]:
    """按本地日期补零的每日行：范围内每天一行，无数据也是 0。

    返回行结构 ``{"date": "YYYY-MM-DD", <9 项指标>}``，日期为租户本地日期。
    """
    tz = _zoneinfo(timezone)
    start, end = _bounds(from_date, to_date, tz)
    maps = _collect_day_maps(
        session, tenant_id=tenant_id, tz=timezone, start=start, end=end
    )

    days: list[dict[str, object]] = []
    current = from_date
    while current <= to_date:
        row: dict[str, object] = {"date": current.isoformat()}
        for key in METRIC_KEYS:
            row[key] = maps[key].get(current, 0)
        days.append(row)
        current += timedelta(days=1)
    return days


def tenant_usage_totals(days: list[dict[str, object]]) -> dict[str, int]:
    """把每日行汇总为区间总量；去重口径在服务层按日去重，跨日不重复去重。"""
    totals = _zero_metrics()
    for row in days:
        for key in METRIC_KEYS:
            totals[key] += int(str(row[key]))
    return totals


def _window_teacher_count(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tz: str,
    start: datetime,
    end: datetime,
) -> int:
    """整窗内有教学操作的去重教师数（不按日重复计数）。"""
    union = _teacher_actor_union(tenant_id, tz, start, end).subquery()
    stmt = select(func.count(func.distinct(union.c.actor)))
    rows = session.connection().execute(stmt).all()
    return int(rows[0][0] or 0)  # type: ignore[arg-type]


def _window_student_count(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> int:
    """整窗内有词汇作答的去重学生数（不按日重复计数）。"""
    stmt = (
        select(func.count(func.distinct(VocabularySession.student_id)))
        .select_from(VocabularyAnswer)
        .join(
            VocabularySession,
            col(VocabularySession.id) == col(VocabularyAnswer.session_id),
        )
        .where(
            col(VocabularyAnswer.tenant_id) == tenant_id,
            col(VocabularyAnswer.answered_at) >= start,  # type: ignore[union-attr]
            col(VocabularyAnswer.answered_at) < end,  # type: ignore[union-attr]
        )
    )
    rows = session.connection().execute(stmt).all()
    return int(rows[0][0] or 0)  # type: ignore[arg-type]


def _window_totals(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    timezone: str,
    from_date: date,
    to_date: date,
) -> dict[str, int]:
    """窗口区间总量：去重项（教师 / 学生）按整窗去重，其余为条数求和。"""
    tz = _zoneinfo(timezone)
    start, end = _bounds(from_date, to_date, tz)
    totals = _zero_metrics()

    totals["active_teachers"] = _window_teacher_count(
        session, tenant_id=tenant_id, tz=timezone, start=start, end=end
    )
    totals["active_students"] = _window_student_count(
        session, tenant_id=tenant_id, start=start, end=end
    )

    def additive(model, time_col, extra_filters=()) -> int:
        stmt = select(func.count()).where(
            col(model.tenant_id) == tenant_id,
            col(time_col) >= start,  # type: ignore[union-attr]
            col(time_col) < end,  # type: ignore[union-attr]
            *extra_filters,
        )
        rows = session.connection().execute(stmt).all()
        return int(rows[0][0] or 0)  # type: ignore[arg-type]

    totals["vocab_answers"] = additive(VocabularyAnswer, VocabularyAnswer.answered_at)
    totals["published_tasks"] = additive(
        VocabularyAssignment, VocabularyAssignment.published_at
    )
    totals["completed_students"] = additive(
        VocabularySession,
        VocabularySession.submitted_at,
        (
            col(VocabularySession.kind) == _SESSION_KIND_TASK,
            col(VocabularySession.status) == _SESSION_STATUS_SUBMITTED,
            col(VocabularySession.submitted_at).is_not(None),
        ),
    )
    totals["pk_matches"] = additive(VocabPkMatch, VocabPkMatch.started_at)
    totals["farm_harvests"] = additive(
        VocabFarmPlot,
        VocabFarmPlot.last_harvested_at,
        (col(VocabFarmPlot.last_harvested_at).is_not(None),),
    )
    totals["placement_tests"] = additive(
        VocabPlacementResult, VocabPlacementResult.submitted_at
    )
    totals["exports"] = additive(
        ExportAudit,
        ExportAudit.created_at,
        (col(ExportAudit.action) == _EXPORT_ACTION_CREATE,),
    )
    return totals


def tenant_usage_summary(
    session: Session,
    tenant: Tenant,
    days_options: tuple[int, ...] = (7, 30),
) -> dict[int, dict[str, int]]:
    """运营列表用的近 N 天核心数（整窗去重 / 条数求和），按 ``days`` 分组返回。"""
    today = today_in_tz(tenant.timezone)
    result: dict[int, dict[str, int]] = {}
    for days in days_options:
        window_from = today - timedelta(days=days - 1)
        result[days] = _window_totals(
            session,
            tenant_id=tenant.id,
            timezone=tenant.timezone,
            from_date=window_from,
            to_date=today,
        )
    return result
