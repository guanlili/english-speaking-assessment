"""题库批量导入导出接口（2026-10-14：老师自助录题、选题、发布）。

    /admin/question-bank/import-template  下载模板（xlsx 分工作表 / CSV 题型列）
    /admin/question-bank/import-preview   上传解析校验（不落库）
    /admin/question-bank/import-confirm   重新上传同一文件，单事务落库
    /admin/question-bank/export            按现有筛选条件导出（格式兼容模板）

普通教师账号即可使用（TeacherUserDep），与管理端建题同权限口径。确认导入
不暂存任何服务端状态：文件重新解析、与库内现状重新比对，预览与确认之间
库或文件发生变化都不会产生脏数据。401 只表示登录失效；权限不足 403。
"""

from typing import Any, Literal

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.deps import SessionDep, TeacherUserDep
from app.models import (
    QuestionBankImportPreview,
    QuestionBankImportResult,
)
from app.services import question_bank_io as io_service

router = APIRouter(prefix="/admin/question-bank", tags=["question-bank"])


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    raw = await file.read()
    if len(raw) > io_service.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 5MB 上限")
    if not raw:
        raise HTTPException(status_code=422, detail="文件为空")
    return file.filename or "", raw


_BINARY_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        }
    }
}


@router.get("/import-template", response_class=Response, responses=_BINARY_RESPONSES)
def download_import_template(
    _teacher: TeacherUserDep,
    format: Literal["xlsx", "csv"] = Query(default="xlsx"),
) -> Response:
    """导入模板：xlsx（按题型分工作表 + 下拉选项 + 说明页）或 CSV（题型列）。"""
    data, filename, media_type = io_service.build_template(format)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import-preview", response_model=QuestionBankImportPreview)
async def question_bank_import_preview(
    session: SessionDep, _teacher: TeacherUserDep, file: UploadFile
) -> Any:
    """导入预览：解析、校验、查重与兜底提示，不落库。"""
    filename, raw = await _read_upload(file)
    # 解析与库内比对都放线程池：async 路由里同步跑会卡住事件循环
    parsed = await run_in_threadpool(io_service.parse_upload, filename, raw)
    return await run_in_threadpool(io_service.preview_import, session, parsed)


@router.post("/import-confirm", response_model=QuestionBankImportResult)
async def question_bank_import_confirm(
    session: SessionDep,
    _teacher: TeacherUserDep,
    file: UploadFile,
    include_suspected: bool = Form(default=False),
) -> Any:
    """确认导入：重新上传预览时的同一文件；疑似重复默认排除，勾选后才导入。"""
    filename, raw = await _read_upload(file)
    parsed = await run_in_threadpool(io_service.parse_upload, filename, raw)
    return await run_in_threadpool(
        io_service.apply_import, session, parsed, include_suspected
    )


@router.get("/export", response_class=Response, responses=_BINARY_RESPONSES)
def export_question_bank(
    session: SessionDep,
    _teacher: TeacherUserDep,
    types: list[str] | None = Query(
        default=None,
        description="题型（passage/repeat/question/instruction，缺省全部）",
    ),
    topic: str | None = Query(default=None, description="主题（篇目/问答）"),
    q: str | None = Query(
        default=None, description="关键词（篇目标题/主题、问答题目/中文提示）"
    ),
    band: str | None = Query(default=None, description="难度 A2/B1/B2（篇目/问答）"),
    exam_kind: str | None = Query(default=None, description="考试题型（复述句/问答）"),
    exam_level: str | None = Query(default=None, description="考试级别（复述句/问答）"),
    active: bool | None = Query(default=None, description="仅篇目：启用状态"),
    format: Literal["xlsx", "csv"] = Query(default="xlsx"),
) -> Response:
    """批量导出：筛选条件镜像现有列表接口；导出格式可直接再次导入。"""
    data, filename, media_type = io_service.export_bank(
        session,
        types=types,
        topic=topic,
        q=q,
        band=band,
        exam_kind=exam_kind,
        exam_level=exam_level,
        active=active,
        fmt=format,
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
