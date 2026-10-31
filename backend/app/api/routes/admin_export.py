"""管理员使用记录 CSV 导出（superuser）：三个口径的下载端点。

实现见 app/services/usage_export.py（2026-10-23 手工 runbook 服务化）。
行数护栏超限（usage_export_too_many_rows）转 422，不产出部分 CSV。
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import PlatformOperatorDep, SessionDep
from app.services import usage_export

router = APIRouter(prefix="/admin/export", tags=["admin"])


def _csv_response(buf, filename: str) -> StreamingResponse:
    # BOM 已在内容首（Excel 直开）；文件名用 ASCII（跨端无编码问题）
    return StreamingResponse(
        buf,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/attempts")
def export_attempts_csv(
    session: SessionDep,
    _operator: PlatformOperatorDep,
    days: int = Query(default=0, ge=0, le=3650, description="0=全部"),
) -> StreamingResponse:
    try:
        buf = usage_export.export_attempts(session, days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _csv_response(buf, "usage-attempts.csv")


@router.get("/sessions")
def export_sessions_csv(
    session: SessionDep,
    _operator: PlatformOperatorDep,
    days: int = Query(default=0, ge=0, le=3650, description="0=全部"),
) -> StreamingResponse:
    try:
        buf = usage_export.export_sessions(session, days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _csv_response(buf, "usage-sessions.csv")


@router.get("/students")
def export_students_csv(
    session: SessionDep,
    _operator: PlatformOperatorDep,
) -> StreamingResponse:
    try:
        buf = usage_export.export_students(session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _csv_response(buf, "usage-students.csv")
