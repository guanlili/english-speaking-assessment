"""导出任务：口语原音频 ZIP，以及学生个人学情 PDF。

学生导出自己的录音或学情报告；教师只导出本人课堂的录音。
学情 PDF 不接受教师代下。一律排队（ExportJob），下载中心轮询进度。
detail 用稳定标识，展示文案由前端双语映射。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import SQLModel, col, func, select

from app.api.deps import CurrentUser, ExportSubmitter, SessionDep
from app.core.config import settings
from app.crud import classroom_teacher_allowed
from app.exporting.worker import delete_artifact, write_audit
from app.models import (
    Classroom,
    ClassroomExercise,
    ExportJob,
    ExportJobStatus,
    ExportKind,
    ExportScope,
    PracticeSession,
    Student,
    User,
    get_datetime_utc,
)
from app.services.audio_export import (
    artifact_file,
    download_name_for,
    present_nbytes,
    query_candidates,
    window_bounds,
)
from app.services.class_report_pdf import (
    class_report_download_name,
)
from app.services.student_report_pdf import (
    report_download_name,
    resolve_report_window,
)

router = APIRouter(prefix="/exports", tags=["exports"])

_IN_PROGRESS = (ExportJobStatus.QUEUED, ExportJobStatus.RUNNING)


class ExportCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope: Literal["self", "classroom"]
    kind: Literal["audio_zip", "student_report_pdf", "class_report_pdf"] = "audio_zip"
    from_at: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    session_id: uuid.UUID | None = None
    exercise_id: uuid.UUID | None = None
    classroom_id: uuid.UUID | None = None
    classroom_code: str | None = None
    # 与 classroom_code 同义，方便按「课堂码」提交学情 PDF
    code: str | None = None
    group_by_item: bool = True
    confirm_contains_student_audio: bool = False
    recent_days: int | None = Field(default=None, ge=1, le=90)
    days: int | None = Field(default=None, ge=1, le=90)


class ExportJobPublic(SQLModel):
    id: uuid.UUID
    scope: str
    kind: str
    status: str
    progress: int
    progress_done: int
    progress_total: int
    error: str | None
    byte_size: int | None
    included_count: int
    missing_count: int
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    downloaded_at: datetime | None
    download_name: str | None
    filter: dict[str, object]


class ExportJobsPublic(SQLModel):
    data: list[ExportJobPublic]
    count: int
    unseen_ready: int


def _public(job: ExportJob) -> ExportJobPublic:
    total = job.progress_total or 0
    done = job.progress_done or 0
    if job.status == ExportJobStatus.SUCCEEDED:
        progress = 100
    elif total <= 0:
        progress = 0
    else:
        progress = min(100, int(done * 100 / total))
    return ExportJobPublic(
        id=job.id,
        scope=job.scope,
        kind=job.kind or ExportKind.AUDIO_ZIP,
        status=job.status,
        progress=progress,
        progress_done=done,
        progress_total=total,
        error=job.error,
        byte_size=job.byte_size,
        included_count=job.included_count,
        missing_count=job.missing_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        expires_at=job.expires_at,
        downloaded_at=job.downloaded_at,
        download_name=job.download_name,
        filter=job.filter_json,
    )


def _inflight(session: SessionDep, user_id: uuid.UUID) -> int:
    return session.exec(
        select(func.count())
        .select_from(ExportJob)
        .where(
            ExportJob.requester_user_id == user_id,
            col(ExportJob.status).in_([*_IN_PROGRESS]),
        )
    ).one()


def _reject(
    session: SessionDep,
    user: User,
    *,
    scope: str,
    result: str,
    detail: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {"result": result}
    if detail:
        payload.update(detail)
    write_audit(
        session,
        job_id=None,
        actor_user_id=user.id,
        action="reject",
        scope=scope,
        detail=payload,
    )
    session.commit()


def _visible(session: SessionDep, job_id: uuid.UUID, user: User) -> ExportJob:
    job = session.get(ExportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.requester_user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="没有权限：只能查看自己的导出任务")
    return job


def _resolve(session: SessionDep, user: User, body: ExportCreate) -> dict[str, object]:
    classroom_name: str | None = None
    classroom_code: str | None = None
    exercise_title: str | None = None
    if body.scope == ExportScope.CLASSROOM:
        if user.role == "student" and not user.is_superuser:
            _reject(session, user, scope=body.scope, result="forbidden")
            raise HTTPException(
                status_code=403,
                detail="没有权限：课堂录音导出仅限该课堂授权教师",
            )
        if body.classroom_id is None:
            raise HTTPException(status_code=422, detail="export_classroom_required")
        classroom = session.get(Classroom, body.classroom_id)
        if classroom is None:
            raise HTTPException(status_code=404, detail="Classroom not found")
        if not classroom_teacher_allowed(classroom, user):
            _reject(
                session,
                user,
                scope=body.scope,
                result="forbidden",
                detail={"classroom_id": str(classroom.id)},
            )
            raise HTTPException(
                status_code=403,
                detail="没有权限：您不是该课堂的授权教师，请联系管理员绑定后再查看",
            )
        if not body.confirm_contains_student_audio:
            _reject(
                session,
                user,
                scope=body.scope,
                result="export_confirm_required",
                detail={"classroom_id": str(classroom.id)},
            )
            raise HTTPException(status_code=422, detail="export_confirm_required")
        if body.exercise_id is not None:
            exercise = session.get(ClassroomExercise, body.exercise_id)
            if exercise is None or exercise.classroom_id != classroom.id:
                raise HTTPException(status_code=422, detail="export_exercise_mismatch")
            exercise_title = exercise.title
        if body.session_id is not None:
            practice = session.get(PracticeSession, body.session_id)
            if practice is None or practice.classroom_id != classroom.id:
                raise HTTPException(status_code=422, detail="export_session_mismatch")
        classroom_name = classroom.name
        classroom_code = classroom.code
    else:
        if body.session_id is not None:
            practice = session.get(PracticeSession, body.session_id)
            student = (
                session.get(Student, practice.student_id)
                if practice is not None
                else None
            )
            if practice is None or student is None or student.user_id != user.id:
                raise HTTPException(
                    status_code=403, detail="没有权限：该练习轮不属于你本人"
                )
        if body.exercise_id is not None:
            exercise = session.get(ClassroomExercise, body.exercise_id)
            if exercise is not None:
                exercise_title = exercise.title
    try:
        start, end = window_bounds(
            scope=body.scope,
            start=body.from_at,
            end=body.to,
            recent_days=body.recent_days,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="export_range_too_wide") from None
    return {
        "scope": body.scope,
        "requester_user_id": str(user.id),
        "classroom_id": str(body.classroom_id) if body.classroom_id else None,
        "classroom_name": classroom_name,
        "classroom_code": classroom_code,
        "exercise_id": str(body.exercise_id) if body.exercise_id else None,
        "exercise_title": exercise_title,
        "session_id": str(body.session_id) if body.session_id else None,
        "from": start.isoformat() if start else None,
        "to": end.isoformat() if end else None,
        "recent_days": body.recent_days,
        "group_by_item": body.group_by_item
        if body.scope == ExportScope.CLASSROOM
        else False,
        "_start": start,
        "_end": end,
        "_classroom_name": classroom_name,
        "_exercise_title": exercise_title,
    }


def _guard_capacity(session: SessionDep, user: User, scope: str) -> None:
    if _inflight(session, user.id) >= settings.EXPORT_MAX_IN_PROGRESS:
        _reject(session, user, scope=scope, result="export_too_many_in_progress")
        raise HTTPException(status_code=429, detail="export_too_many_in_progress")


def _report_code(body: ExportCreate) -> str | None:
    raw = (body.classroom_code or body.code or "").strip()
    return raw or None


def _create_student_report(
    session: SessionDep,
    current_user: User,
    body: ExportCreate,
    submitter: ExportSubmitter,
) -> ExportJobPublic:
    """学生导出自己的学情 PDF。教师代下直接 403，不建任务。"""
    if body.scope != ExportScope.SELF or current_user.role != "student":
        _reject(
            session,
            current_user,
            scope=body.scope,
            result="export_report_student_only",
        )
        raise HTTPException(status_code=403, detail="export_report_student_only")
    code = _report_code(body)
    classroom: Classroom | None = None
    if body.classroom_id is not None:
        classroom = session.get(Classroom, body.classroom_id)
        if classroom is None:
            raise HTTPException(status_code=404, detail="Classroom not found")
    if code is not None:
        by_code = session.exec(select(Classroom).where(Classroom.code == code)).first()
        if by_code is None and code.upper() != code:
            by_code = session.exec(
                select(Classroom).where(Classroom.code == code.upper())
            ).first()
        if by_code is None:
            raise HTTPException(status_code=404, detail="Classroom not found")
        if classroom is not None and by_code.id != classroom.id:
            raise HTTPException(status_code=422, detail="export_classroom_mismatch")
        classroom = by_code
    if classroom is None:
        raise HTTPException(status_code=422, detail="export_classroom_required")
    student = session.exec(
        select(Student).where(
            Student.user_id == current_user.id,
            Student.classroom_id == classroom.id,
        )
    ).first()
    if student is None or student.user_id != current_user.id:
        _reject(
            session,
            current_user,
            scope=body.scope,
            result="export_report_forbidden",
            detail={"classroom_id": str(classroom.id)},
        )
        raise HTTPException(status_code=403, detail="export_report_forbidden")
    exercise_title: str | None = None
    if body.exercise_id is not None:
        exercise = session.get(ClassroomExercise, body.exercise_id)
        if exercise is None or exercise.classroom_id != classroom.id:
            raise HTTPException(status_code=422, detail="export_exercise_mismatch")
        exercise_title = exercise.title
    try:
        start, end = resolve_report_window(
            start=body.from_at,
            end=body.to,
            days=body.days,
            recent_days=body.recent_days,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="export_range_too_wide") from None
    _guard_capacity(session, current_user, body.scope)
    filt: dict[str, object] = {
        "kind": ExportKind.STUDENT_REPORT_PDF,
        "scope": ExportScope.SELF,
        "requester_user_id": str(current_user.id),
        "classroom_id": str(classroom.id),
        "classroom_code": classroom.code,
        "exercise_id": str(body.exercise_id) if body.exercise_id else None,
        "exercise_title": exercise_title,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": body.days,
        "recent_days": body.recent_days,
    }
    name = report_download_name(
        student_name=student.display_name,
        start=start,
        end=end,
    )
    job = ExportJob(
        requester_user_id=current_user.id,
        scope=ExportScope.SELF,
        kind=ExportKind.STUDENT_REPORT_PDF,
        filter_json=filt,
        status=ExportJobStatus.QUEUED,
        download_name=name,
        confirm_contains_student_audio=False,
    )
    session.add(job)
    session.flush()
    write_audit(
        session,
        job_id=job.id,
        actor_user_id=current_user.id,
        action="create",
        scope=ExportScope.SELF,
        detail={"result": "queued", "filter": filt},
    )
    session.commit()
    session.refresh(job)
    submitter(job.id)
    session.refresh(job)
    return _public(job)


def _create_class_report(
    session: SessionDep,
    current_user: User,
    body: ExportCreate,
    submitter: ExportSubmitter,
) -> ExportJobPublic:
    """教师导出自己班级的分析报告 PDF。仅本班 owner/管理员；学生 403。"""
    if current_user.role == "student":
        _reject(
            session,
            current_user,
            scope=body.scope,
            result="export_class_report_teacher_only",
        )
        raise HTTPException(status_code=403, detail="export_class_report_teacher_only")
    if body.exercise_id is not None or body.session_id is not None:
        raise HTTPException(status_code=422, detail="export_exercise_not_supported")
    code = _report_code(body)
    classroom: Classroom | None = None
    if body.classroom_id is not None:
        classroom = session.get(Classroom, body.classroom_id)
        if classroom is None:
            raise HTTPException(status_code=404, detail="Classroom not found")
    if code is not None:
        by_code = session.exec(select(Classroom).where(Classroom.code == code)).first()
        if by_code is None and code.upper() != code:
            by_code = session.exec(
                select(Classroom).where(Classroom.code == code.upper())
            ).first()
        if by_code is None:
            raise HTTPException(status_code=404, detail="Classroom not found")
        if classroom is not None and by_code.id != classroom.id:
            raise HTTPException(status_code=422, detail="export_classroom_mismatch")
        classroom = by_code
    if classroom is None:
        raise HTTPException(status_code=422, detail="export_classroom_required")
    if not classroom_teacher_allowed(classroom, current_user):
        _reject(
            session,
            current_user,
            scope=body.scope,
            result="forbidden",
            detail={"classroom_id": str(classroom.id)},
        )
        raise HTTPException(
            status_code=403,
            detail="没有权限：您不是该课堂的授权教师，请联系管理员绑定后再查看",
        )
    try:
        start, end = resolve_report_window(
            start=body.from_at,
            end=body.to,
            days=body.days,
            recent_days=body.recent_days,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="export_range_too_wide") from None
    _guard_capacity(session, current_user, body.scope)
    filt: dict[str, object] = {
        "kind": ExportKind.CLASS_REPORT_PDF,
        "scope": ExportScope.CLASSROOM,
        "requester_user_id": str(current_user.id),
        "classroom_id": str(classroom.id),
        "classroom_code": classroom.code,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "recent_days": body.recent_days,
    }
    name = class_report_download_name(
        classroom_name=classroom.name, start=start, end=end
    )
    job = ExportJob(
        requester_user_id=current_user.id,
        scope=ExportScope.CLASSROOM,
        kind=ExportKind.CLASS_REPORT_PDF,
        filter_json=filt,
        status=ExportJobStatus.QUEUED,
        download_name=name,
        confirm_contains_student_audio=False,
    )
    session.add(job)
    session.flush()
    write_audit(
        session,
        job_id=job.id,
        actor_user_id=current_user.id,
        action="create",
        scope=ExportScope.CLASSROOM,
        detail={"result": "queued", "filter": filt},
    )
    session.commit()
    session.refresh(job)
    submitter(job.id)
    session.refresh(job)
    return _public(job)


@router.post("", response_model=ExportJobPublic)
def create_export(
    session: SessionDep,
    current_user: CurrentUser,
    body: ExportCreate,
    submitter: ExportSubmitter,
) -> ExportJobPublic:
    """创建导出任务并立即返回。打包在独立线程池里进行。"""
    if body.kind == ExportKind.STUDENT_REPORT_PDF:
        return _create_student_report(session, current_user, body, submitter)
    if body.kind == ExportKind.CLASS_REPORT_PDF:
        return _create_class_report(session, current_user, body, submitter)
    resolved = _resolve(session, current_user, body)
    _guard_capacity(session, current_user, body.scope)
    filt = {key: value for key, value in resolved.items() if not key.startswith("_")}
    filt["kind"] = ExportKind.AUDIO_ZIP
    try:
        candidates = query_candidates(session, filt)
    except ValueError as exc:
        # 行数护栏超限（export_too_many_attempts）：拒绝并留档，不入队
        _reject(
            session,
            current_user,
            scope=body.scope,
            result=str(exc),
            detail={"max_rows": settings.EXPORT_MAX_ROWS},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from None
    # 体积预检不持有行锁；超限直接拒绝，不排队、不分卷。
    session.commit()
    if present_nbytes(candidates) > settings.EXPORT_MAX_BYTES:
        _reject(
            session,
            current_user,
            scope=body.scope,
            result="export_too_large",
            detail={"bytes": present_nbytes(candidates)},
        )
        raise HTTPException(status_code=422, detail="export_too_large")
    now = get_datetime_utc()
    raw_classroom = resolved.get("_classroom_name")
    raw_exercise = resolved.get("_exercise_title")
    raw_start = resolved.get("_start")
    raw_end = resolved.get("_end")
    classroom_name = raw_classroom if isinstance(raw_classroom, str) else None
    exercise_title = raw_exercise if isinstance(raw_exercise, str) else None
    start = raw_start if isinstance(raw_start, datetime) else None
    end = raw_end if isinstance(raw_end, datetime) else None
    name = download_name_for(
        scope=body.scope,
        classroom_name=classroom_name,
        exercise_title=exercise_title,
        start=start,
        end=end,
        now=now,
    )
    job = ExportJob(
        requester_user_id=current_user.id,
        scope=body.scope,
        kind=ExportKind.AUDIO_ZIP,
        filter_json=filt,
        status=ExportJobStatus.QUEUED,
        download_name=name,
        confirm_contains_student_audio=body.confirm_contains_student_audio,
    )
    session.add(job)
    session.flush()
    write_audit(
        session,
        job_id=job.id,
        actor_user_id=current_user.id,
        action="create",
        scope=body.scope,
        detail={"result": "queued", "filter": filt},
    )
    session.commit()
    session.refresh(job)
    submitter(job.id)
    session.refresh(job)
    return _public(job)


@router.get("", response_model=ExportJobsPublic)
def list_exports(session: SessionDep, current_user: CurrentUser) -> ExportJobsPublic:
    """下载中心：只列出当前账号自己的任务。"""
    rows = session.exec(
        select(ExportJob)
        .where(ExportJob.requester_user_id == current_user.id)
        .order_by(col(ExportJob.created_at).desc())
        .limit(100)
    ).all()
    now = get_datetime_utc()
    unseen = session.exec(
        select(func.count())
        .select_from(ExportJob)
        .where(
            ExportJob.requester_user_id == current_user.id,
            ExportJob.status == ExportJobStatus.SUCCEEDED,
            col(ExportJob.downloaded_at).is_(None),
            col(ExportJob.expires_at).is_not(None),
            col(ExportJob.expires_at) > now,
        )
    ).one()
    return ExportJobsPublic(
        data=[_public(row) for row in rows],
        count=len(rows),
        unseen_ready=int(unseen),
    )


@router.get("/{job_id}", response_model=ExportJobPublic)
def read_export(
    session: SessionDep, job_id: uuid.UUID, current_user: CurrentUser
) -> ExportJobPublic:
    return _public(_visible(session, job_id, current_user))


def _expire_job(session: SessionDep, job: ExportJob) -> None:
    delete_artifact(job.artifact_relpath)
    if job.status != ExportJobStatus.EXPIRED:
        job.status = ExportJobStatus.EXPIRED
        job.artifact_relpath = None
        session.add(job)
        write_audit(
            session,
            job_id=job.id,
            actor_user_id=job.requester_user_id,
            action="expire",
            scope=job.scope,
            detail={"result": "expired"},
        )
        session.commit()


@router.get("/{job_id}/download")
def download_export(
    session: SessionDep, job_id: uuid.UUID, current_user: CurrentUser
) -> FileResponse:
    job = _visible(session, job_id, current_user)
    now = get_datetime_utc()
    if job.status == ExportJobStatus.EXPIRED or (
        job.expires_at is not None and job.expires_at <= now
    ):
        _expire_job(session, job)
        raise HTTPException(status_code=410, detail="export_expired")
    if job.status != ExportJobStatus.SUCCEEDED:
        raise HTTPException(status_code=409, detail="export_not_ready")
    path = artifact_file(job.artifact_relpath)
    if path is None or not path.is_file():
        _expire_job(session, job)
        raise HTTPException(status_code=410, detail="export_expired")
    job.downloaded_at = now
    session.add(job)
    write_audit(
        session,
        job_id=job.id,
        actor_user_id=current_user.id,
        action="download",
        scope=job.scope,
        detail={"result": "downloaded", "byte_size": job.byte_size},
    )
    session.commit()
    is_pdf = job.kind == ExportKind.STUDENT_REPORT_PDF or (
        (job.download_name or "").lower().endswith(".pdf")
    )
    ascii_name = "SpeakUp_report.pdf" if is_pdf else "SpeakUp_export.zip"
    filename = job.download_name or ascii_name
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    )
    return FileResponse(
        path,
        media_type="application/pdf" if is_pdf else "application/zip",
        headers={"Content-Disposition": disposition},
    )


@router.post("/{job_id}/retry", response_model=ExportJobPublic)
def retry_export(
    session: SessionDep,
    job_id: uuid.UUID,
    current_user: CurrentUser,
    submitter: ExportSubmitter,
) -> ExportJobPublic:
    job = _visible(session, job_id, current_user)
    if job.requester_user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="没有权限：只能查看自己的导出任务")
    if job.status != ExportJobStatus.FAILED:
        raise HTTPException(status_code=409, detail="export_retry_not_failed")
    if _inflight(session, job.requester_user_id) >= settings.EXPORT_MAX_IN_PROGRESS:
        _reject(
            session,
            current_user,
            scope=job.scope,
            result="export_too_many_in_progress",
        )
        raise HTTPException(status_code=429, detail="export_too_many_in_progress")
    delete_artifact(job.artifact_relpath)
    job.status = ExportJobStatus.QUEUED
    job.error = None
    job.artifact_relpath = None
    job.byte_size = None
    job.included_count = 0
    job.missing_count = 0
    job.progress_done = 0
    job.progress_total = 0
    job.started_at = None
    job.finished_at = None
    job.expires_at = None
    job.downloaded_at = None
    session.add(job)
    write_audit(
        session,
        job_id=job.id,
        actor_user_id=current_user.id,
        action="retry",
        scope=job.scope,
        detail={"result": "queued", "filter": job.filter_json},
    )
    session.commit()
    session.refresh(job)
    submitter(job.id)
    session.refresh(job)
    return _public(job)
