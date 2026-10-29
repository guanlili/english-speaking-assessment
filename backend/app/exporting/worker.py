"""导出任务线程池。

独立于评分 ThreadPoolExecutor，工人数上限 2，不读取 SCORING_WORKERS。
慢操作（打包）在事务外进行：短事务领取 → 释放 → 写 ZIP → 短事务落结果。
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    ExportAudit,
    ExportJob,
    ExportJobStatus,
    ExportKind,
    get_datetime_utc,
)
from app.services.audio_export import (
    build_zip,
    export_directory,
    present_nbytes,
    query_candidates,
    root_from_download_name,
)

logger = logging.getLogger("app.export")

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_executor_stopped = False

SWEEP_INTERVAL_S = 60 * 60
_sweeper_stop: threading.Event | None = None
_sweeper_thread: threading.Thread | None = None


def worker_count() -> int:
    """导出池规模。硬上限 2，且与评分池配置无关。"""
    raw = settings.EXPORT_WORKERS
    if raw > 2:
        logger.warning("EXPORT_WORKERS=%s capped at 2", raw)
    return max(1, min(2, raw))


def _ensure_executor_locked() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        if _executor_stopped:
            raise RuntimeError(
                "export executor stopped; cannot recreate after final shutdown"
            )
        _executor = ThreadPoolExecutor(
            max_workers=worker_count(),
            thread_name_prefix="export",
        )
    return _executor


def get_executor() -> ThreadPoolExecutor:
    if _executor is None:
        with _executor_lock:
            _ensure_executor_locked()
    assert _executor is not None
    return _executor


def submit_export_job(job_id: UUID) -> None:
    with _executor_lock:
        if _executor_stopped:
            logger.info("export executor stopped; skip submit for %s", job_id)
            return
        executor = _ensure_executor_locked()
    executor.submit(copy_context().run, _run, job_id)


def reset_executor_for_restart() -> None:
    global _executor_stopped
    with _executor_lock:
        _executor_stopped = False


def shutdown_executor(final: bool = True) -> None:
    global _executor, _executor_stopped
    with _executor_lock:
        if final:
            _executor_stopped = True
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None


def write_audit(
    session: Session,
    *,
    job_id: UUID | None,
    actor_user_id: UUID,
    action: str,
    scope: str | None,
    detail: dict[str, object] | None,
) -> None:
    session.add(
        ExportAudit(
            job_id=job_id,
            actor_user_id=actor_user_id,
            action=action,
            scope=scope,
            detail=detail,
        )
    )
    logger.info(
        "export_audit action=%s job_id=%s actor=%s scope=%s result=%s",
        action,
        job_id,
        actor_user_id,
        scope,
        None if detail is None else detail.get("result"),
    )


def _claim(session: Session, job_id: UUID) -> ExportJob | None:
    job = session.exec(
        select(ExportJob)
        .where(ExportJob.id == job_id)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None or job.status != ExportJobStatus.QUEUED:
        return None
    job.status = ExportJobStatus.RUNNING
    job.started_at = get_datetime_utc()
    job.error = None
    session.add(job)
    write_audit(
        session,
        job_id=job.id,
        actor_user_id=job.requester_user_id,
        action="start",
        scope=job.scope,
        detail={"result": "running", "filter": job.filter_json},
    )
    session.commit()
    session.refresh(job)
    return job


def _progress(job_id: UUID, done: int, total: int) -> None:
    from app.core.db import engine

    with Session(engine) as session:
        job = session.get(ExportJob, job_id)
        if job is None or job.status != ExportJobStatus.RUNNING:
            return
        job.progress_done = done
        job.progress_total = total
        session.add(job)
        session.commit()


def _finish_failed(
    job_id: UUID,
    *,
    error: str,
    included: int,
    missing: int,
    total: int,
) -> None:
    from app.core.db import engine

    with Session(engine) as session:
        job = session.get(ExportJob, job_id)
        if job is None or job.status != ExportJobStatus.RUNNING:
            logger.error("export job %s missing while recording failure", job_id)
            return
        job.status = ExportJobStatus.FAILED
        job.error = error[:512]
        job.finished_at = get_datetime_utc()
        job.included_count = included
        job.missing_count = missing
        job.progress_done = total
        job.progress_total = total
        job.artifact_relpath = None
        job.byte_size = None
        session.add(job)
        write_audit(
            session,
            job_id=job.id,
            actor_user_id=job.requester_user_id,
            action="fail",
            scope=job.scope,
            detail={
                "result": error,
                "included": included,
                "missing": missing,
                "filter": job.filter_json,
            },
        )
        session.commit()


def _finish_ok(
    job_id: UUID,
    *,
    included: int,
    missing: int,
    total: int,
    artifact: str,
    byte_size: int,
) -> None:
    from app.core.db import engine

    with Session(engine) as session:
        job = session.get(ExportJob, job_id)
        if job is None or job.status != ExportJobStatus.RUNNING:
            logger.error("export job %s missing while recording success", job_id)
            return
        now = get_datetime_utc()
        job.status = ExportJobStatus.SUCCEEDED
        job.error = None
        job.finished_at = now
        job.expires_at = now + timedelta(days=max(settings.EXPORT_TTL_DAYS, 0))
        job.included_count = included
        job.missing_count = missing
        job.progress_done = total
        job.progress_total = total
        job.artifact_relpath = artifact
        job.byte_size = byte_size
        session.add(job)
        write_audit(
            session,
            job_id=job.id,
            actor_user_id=job.requester_user_id,
            action="success",
            scope=job.scope,
            detail={
                "result": "succeeded",
                "included": included,
                "missing": missing,
                "byte_size": byte_size,
                "filter": job.filter_json,
            },
        )
        session.commit()


def process_export_job(job_id: UUID) -> None:
    """领取并完成一个任务。ZIP 与学情 PDF 分路，失败写入 error，不吞掉异常。"""
    from app.core.db import engine

    with Session(engine) as session:
        job = _claim(session, job_id)
        if job is None:
            return
        kind = job.kind or ExportKind.AUDIO_ZIP
        filt = dict(job.filter_json)
        scope = job.scope
        group_by_item = bool(filt.get("group_by_item", True))
        download_name = job.download_name
        requester_user_id = job.requester_user_id
        candidates = (
            None
            if kind in (ExportKind.STUDENT_REPORT_PDF, ExportKind.CLASS_REPORT_PDF)
            else query_candidates(session, filt)
        )
    if kind == ExportKind.STUDENT_REPORT_PDF:
        _process_student_report(job_id, filt, requester_user_id)
        return
    if kind == ExportKind.CLASS_REPORT_PDF:
        _process_class_report(job_id, filt, requester_user_id)
        return
    assert candidates is not None
    try:
        if present_nbytes(candidates) > settings.EXPORT_MAX_BYTES:
            _finish_failed(
                job_id,
                error="export_too_large",
                included=0,
                missing=len(candidates),
                total=len(candidates),
            )
            return
        root = root_from_download_name(download_name)
        dest = export_directory() / f"{job_id}.zip"

        def on_progress(done: int, total: int) -> None:
            _progress(job_id, done, total)

        result = build_zip(
            candidates,
            scope=scope,
            group_by_item=group_by_item,
            root_name=root,
            dest=dest,
            on_progress=on_progress,
        )
    except Exception as exc:
        logger.exception("export job %s failed", job_id)
        message = f"export_failed: {exc}"[:512]
        try:
            _finish_failed(
                job_id,
                error=message,
                included=0,
                missing=0,
                total=0,
            )
        except Exception:
            logger.exception("export job %s could not record failure", job_id)
            raise
        return
    if result.error or result.artifact_name is None:
        _finish_failed(
            job_id,
            error=result.error or "export_failed",
            included=result.included,
            missing=result.missing,
            total=len(candidates),
        )
        return
    _finish_ok(
        job_id,
        included=result.included,
        missing=result.missing,
        total=len(candidates),
        artifact=result.artifact_name,
        byte_size=result.byte_size,
    )


def _process_class_report(
    job_id: UUID,
    filt: dict[str, object],
    requester_user_id: UUID,
) -> None:
    """班级分析 PDF：与学情 PDF 同构——短事务读、事务外排版、短事务写结果。"""
    from app.core.db import engine
    from app.services.audio_export import export_directory
    from app.services.class_report_pdf import (
        ReportForbidden,
        load_class_report,
        render_class_report,
    )

    try:
        with Session(engine) as session:
            report = load_class_report(session, filt, requester_user_id)
    except ReportForbidden:
        _finish_failed(
            job_id,
            error="export_report_forbidden",
            included=0,
            missing=0,
            total=0,
        )
        return
    except ValueError as exc:
        code = str(exc)
        _finish_failed(
            job_id,
            error=code if code.startswith("export_") else "export_failed",
            included=0,
            missing=0,
            total=0,
        )
        return
    except Exception as exc:
        logger.exception("export job %s failed while reading the class report", job_id)
        _finish_failed(
            job_id,
            error=f"export_failed: {exc}"[:512],
            included=0,
            missing=0,
            total=0,
        )
        return
    dest = export_directory() / f"{job_id}.pdf"
    try:
        result = render_class_report(report, dest)
    except Exception as exc:
        logger.exception("export job %s failed while rendering class pdf", job_id)
        dest.unlink(missing_ok=True)
        try:
            _finish_failed(
                job_id,
                error=f"export_failed: {exc}"[:512],
                included=0,
                missing=0,
                total=0,
            )
        except Exception:
            logger.exception("export job %s could not record failure", job_id)
            raise
        return
    if result.byte_size > settings.REPORT_PDF_MAX_BYTES:
        dest.unlink(missing_ok=True)
        _finish_failed(
            job_id,
            error="export_pdf_too_large",
            included=result.included,
            missing=0,
            total=max(result.included, 1),
        )
        return
    _finish_ok(
        job_id,
        included=result.included,
        missing=0,
        total=max(result.included, 1),
        artifact=result.artifact_name,
        byte_size=result.byte_size,
    )


def _process_student_report(
    job_id: UUID,
    filt: dict[str, object],
    requester_user_id: UUID,
) -> None:
    """学情 PDF：短事务读数据，释放后再排版落盘，最后短事务写结果。"""
    from app.core.db import engine
    from app.services.audio_export import export_directory
    from app.services.student_report_pdf import (
        ReportForbidden,
        load_student_report,
        render_student_report,
    )

    try:
        with Session(engine) as session:
            report = load_student_report(session, filt, requester_user_id)
    except ReportForbidden:
        _finish_failed(
            job_id,
            error="export_report_forbidden",
            included=0,
            missing=0,
            total=0,
        )
        return
    except ValueError as exc:
        code = str(exc)
        _finish_failed(
            job_id,
            error=code if code.startswith("export_") else "export_failed",
            included=0,
            missing=0,
            total=0,
        )
        return
    except Exception as exc:
        logger.exception("export job %s failed while reading the report", job_id)
        _finish_failed(
            job_id,
            error=f"export_failed: {exc}"[:512],
            included=0,
            missing=0,
            total=0,
        )
        return
    dest = export_directory() / f"{job_id}.pdf"
    try:
        result = render_student_report(report, dest)
    except Exception as exc:
        logger.exception("export job %s failed while rendering pdf", job_id)
        dest.unlink(missing_ok=True)
        try:
            _finish_failed(
                job_id,
                error=f"export_failed: {exc}"[:512],
                included=0,
                missing=0,
                total=0,
            )
        except Exception:
            logger.exception("export job %s could not record failure", job_id)
            raise
        return
    if result.byte_size > settings.REPORT_PDF_MAX_BYTES:
        dest.unlink(missing_ok=True)
        _finish_failed(
            job_id,
            error="export_pdf_too_large",
            included=result.included,
            missing=0,
            total=max(result.included, 1),
        )
        return
    _finish_ok(
        job_id,
        included=result.included,
        missing=0,
        total=max(result.included, 1),
        artifact=result.artifact_name,
        byte_size=result.byte_size,
    )


def _run(job_id: UUID) -> None:
    process_export_job(job_id)


def delete_artifact(relpath: str | None) -> None:
    from app.services.audio_export import artifact_file

    path = artifact_file(relpath)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("failed to delete export artifact %s", path)


def expire_due_exports(session: Session) -> int:
    """到期成品：删文件、状态改为 expired、写审计。"""
    now = datetime.now(UTC)
    jobs = session.exec(
        select(ExportJob).where(
            ExportJob.status == ExportJobStatus.SUCCEEDED,
            col(ExportJob.expires_at).is_not(None),
            col(ExportJob.expires_at) <= now,
        )
    ).all()
    expired = 0
    for job in jobs:
        delete_artifact(job.artifact_relpath)
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
        expired += 1
    if expired:
        session.commit()
    return expired


def startup_recovery() -> None:
    """进程重启后：运行中的任务退回队列并重投，同时清一次到期成品。"""
    from app.core.db import engine

    with Session(engine) as session:
        running = session.exec(
            select(ExportJob).where(ExportJob.status == ExportJobStatus.RUNNING)
        ).all()
        for job in running:
            job.status = ExportJobStatus.QUEUED
            job.started_at = None
            session.add(job)
        if running:
            session.commit()
        queued_ids = list(
            session.exec(
                select(ExportJob.id).where(ExportJob.status == ExportJobStatus.QUEUED)
            ).all()
        )
        expire_due_exports(session)
    for job_id in queued_ids:
        submit_export_job(job_id)


def _sweep_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(SWEEP_INTERVAL_S):
        from app.core.db import engine

        try:
            with Session(engine) as session:
                expire_due_exports(session)
        except Exception:
            logger.exception("export sweeper iteration failed")


def start_sweeper() -> None:
    global _sweeper_stop, _sweeper_thread
    if _sweeper_thread is not None and _sweeper_thread.is_alive():
        return
    _sweeper_stop = threading.Event()
    _sweeper_thread = threading.Thread(
        target=_sweep_loop,
        args=(_sweeper_stop,),
        name="export-sweeper",
        daemon=True,
    )
    _sweeper_thread.start()


def stop_sweeper() -> None:
    global _sweeper_stop, _sweeper_thread
    if _sweeper_stop is not None:
        _sweeper_stop.set()
    _sweeper_stop = None
    _sweeper_thread = None
