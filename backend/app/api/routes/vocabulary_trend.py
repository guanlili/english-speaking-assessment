"""教师跨任务 / 时间趋势接口（#517 C）。

    GET /classes/{code}/vocabulary/trend        周期趋势 JSON
    GET /classes/{code}/vocabulary/trend.csv    同口径 CSV 导出

权限口径与既有班级词汇端点一致：课堂不存在 / 跨校 → 404；非本班教师 → 403；
vocabulary 模块未开通 → 403。趋势为教学参考，不是考试分数或能力认证。
"""

import io
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import SessionDep, TeacherUserDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
)
from app.models import (
    VocabularyTrendPeriod,
    VocabularyTrendReport,
)
from app.services import vocabulary as vocab_service
from app.services import vocabulary_trend

router = APIRouter()

CSV_COLUMNS = [
    "周期",
    "period_start",
    "period_end",
    "目标数",
    "完成数",
    "完成率",
    "首答数",
    "首答正确",
    "首答正确率",
    "低分段",
    "中分段",
    "高分段",
    "无数据",
    "到期未复习",
]


def _resolve_trend(
    session: SessionDep,
    code: str,
    current_user: TeacherUserDep,
    granularity: str,
    periods: int,
    anchor: date | None,
    book_id: uuid.UUID | None,
    prompt_type: str | None,
) -> VocabularyTrendReport:
    """权限校验 + 参数校验 + 聚合（JSON / CSV 共用同一事实源）。"""
    if granularity not in vocabulary_trend.GRANULARITIES:
        raise HTTPException(
            status_code=422,
            detail=f"未知周期粒度：{granularity}（可选：week/month）",
        )
    if prompt_type is not None:
        vocab_service.validate_prompt_types([prompt_type])

    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user, "vocabulary")
    return vocabulary_trend.build_trend_report(
        session,
        classroom=classroom,
        granularity=granularity,
        periods=periods,
        anchor=anchor,
        book_id=book_id,
        prompt_type=prompt_type,
    )


@router.get(
    "/classes/{code}/vocabulary/trend",
    response_model=VocabularyTrendReport,
)
def get_vocabulary_trend(
    session: SessionDep,
    code: str,
    current_user: TeacherUserDep,
    granularity: str = Query(..., description="week=按周；month=按月"),
    periods: int = Query(
        vocabulary_trend.DEFAULT_PERIODS,
        ge=vocabulary_trend.MIN_PERIODS,
        le=vocabulary_trend.MAX_PERIODS,
    ),
    anchor: date | None = Query(None, description="锚定日期 YYYY-MM-DD，缺省=今天"),
    book_id: uuid.UUID | None = Query(None, description="按来源词库筛选"),
    prompt_type: str | None = Query(None, description="按出题方式筛选"),
) -> Any:
    """班级词汇趋势：完成率 / 首答正确率 / 掌握度分段 / 到期未复习。"""
    return _resolve_trend(
        session,
        code,
        current_user,
        granularity,
        periods,
        anchor,
        book_id,
        prompt_type,
    )


def _csv_cell(value: int | str | None) -> str:
    """空值留空，不写 0；数值直接落字符串。"""
    return "" if value is None else str(value)


def _period_csv_row(period: VocabularyTrendPeriod) -> list[str]:
    span = f"{period.period_start} ~ {period.period_end}"
    return [
        span,
        str(period.period_start),
        str(period.period_end),
        str(period.assigned_targets),
        str(period.completed_targets),
        _csv_cell(period.completion_rate),
        str(period.first_answered),
        str(period.first_correct),
        _csv_cell(period.first_accuracy),
        str(period.low_count),
        str(period.mid_count),
        str(period.high_count),
        str(period.no_data_count),
        str(period.due_unreviewed),
    ]


@router.get("/classes/{code}/vocabulary/trend.csv")
def get_vocabulary_trend_csv(
    session: SessionDep,
    code: str,
    current_user: TeacherUserDep,
    granularity: str = Query(...),
    periods: int = Query(
        vocabulary_trend.DEFAULT_PERIODS,
        ge=vocabulary_trend.MIN_PERIODS,
        le=vocabulary_trend.MAX_PERIODS,
    ),
    anchor: date | None = Query(None),
    book_id: uuid.UUID | None = Query(None),
    prompt_type: str | None = Query(None),
) -> Response:
    """趋势 CSV（UTF-8 BOM）：一行一周期；空值留空，不写 0。"""
    report = _resolve_trend(
        session,
        code,
        current_user,
        granularity,
        periods,
        anchor,
        book_id,
        prompt_type,
    )
    buffer = io.StringIO()
    buffer.write(",".join(CSV_COLUMNS) + "\n")
    for period in report.items:
        buffer.write(",".join(_period_csv_row(period)) + "\n")
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vocabulary-trend.csv"'},
    )
