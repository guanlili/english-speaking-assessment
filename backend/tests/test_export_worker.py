"""导出 worker 状态机：领取、进度、成功/失败收尾、过期清理、重启恢复。

这些分支平时只在"导出失败/重启/成品到期"时才走，出了问题表现为
"点了导出没反应"或"文件下载 410"，所以单独锁住。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.exporting import worker as export_worker
from app.models import (
    DEFAULT_TENANT_ID,
    ExportAudit,
    ExportJob,
    ExportJobStatus,
    ExportKind,
    ExportScope,
    User,
)


def _engine() -> Any:
    """延迟取引擎：worker 内部也是函数内 import，这样才能落到测试库。

    顶层 `from app.core.db import platform_engine` 会被收集阶段固化成默认
    （开发/生产）引擎，测试随后断言的对象就落到另一个库里。
    """
    from app.core.db import platform_engine

    return platform_engine


@pytest.fixture(autouse=True)
def _clean_executor() -> Any:
    """每个用例后把线程池恢复原状，避免污染后续测试。"""
    yield
    export_worker.shutdown_executor(final=False)
    export_worker.reset_executor_for_restart()


@pytest.fixture
def make_job() -> Any:
    created: list[uuid.UUID] = []

    def _make(**overrides: Any) -> uuid.UUID:
        with Session(_engine()) as session:
            requester = session.exec(select(User)).first()
            assert requester is not None, "测试库缺少初始用户"
            job = ExportJob(
                requester_user_id=requester.id,
                scope=overrides.pop("scope", ExportScope.SELF),
                kind=overrides.pop("kind", ExportKind.AUDIO_ZIP),
                filter_json=overrides.pop("filter_json", {}),
                status=overrides.pop("status", ExportJobStatus.QUEUED),
                **overrides,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            created.append(job.id)
            return job.id

    yield _make

    with Session(_engine()) as session:
        session.exec(delete(ExportAudit).where(col(ExportAudit.job_id).in_(created)))
        session.exec(delete(ExportJob).where(col(ExportJob.id).in_(created)))
        session.commit()


def _load(job_id: uuid.UUID) -> ExportJob:
    with Session(_engine()) as session:
        job = session.get(ExportJob, job_id)
        assert job is not None
        return job


def test_worker_count_caps_at_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EXPORT_WORKERS", 8)
    assert export_worker.worker_count() == 2
    monkeypatch.setattr(settings, "EXPORT_WORKERS", 0)
    assert export_worker.worker_count() == 1
    monkeypatch.setattr(settings, "EXPORT_WORKERS", 2)
    assert export_worker.worker_count() == 2


def test_submit_skipped_after_final_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_worker.shutdown_executor(final=True)
    submitted: list[uuid.UUID] = []
    monkeypatch.setattr(export_worker, "_run", lambda job_id: submitted.append(job_id))
    export_worker.submit_export_job(uuid.uuid4())
    assert submitted == []


def test_executor_cannot_be_recreated_after_final_shutdown() -> None:
    export_worker.shutdown_executor(final=True)
    with pytest.raises(RuntimeError, match="stopped"):
        export_worker.get_executor()
    # reset 之后（模拟进程重启）允许重建
    export_worker.reset_executor_for_restart()
    assert export_worker.get_executor() is not None


def test_claim_moves_queued_to_running(make_job: Any) -> None:
    job_id = make_job()
    with Session(_engine()) as session:
        claimed = export_worker._claim(session, job_id)  # noqa: SLF001
    assert claimed is not None
    assert claimed.status == ExportJobStatus.RUNNING
    assert claimed.started_at is not None
    with Session(_engine()) as session:
        audits = session.exec(
            select(ExportAudit).where(ExportAudit.job_id == job_id)
        ).all()
    assert any(a.action == "start" for a in audits)


def test_claim_returns_none_for_missing_or_unfinished_state(make_job: Any) -> None:
    with Session(_engine()) as session:
        assert export_worker._claim(session, uuid.uuid4()) is None  # noqa: SLF001

    running = make_job(status=ExportJobStatus.RUNNING)
    with Session(_engine()) as session:
        # 已被别的 worker 领走：不能重复领取（skip_locked 语义的落点）
        assert export_worker._claim(session, running) is None  # noqa: SLF001


def test_progress_only_touches_running_job(make_job: Any) -> None:
    running = make_job(status=ExportJobStatus.RUNNING)
    export_worker._progress(running, 3, 10)  # noqa: SLF001
    job = _load(running)
    assert (job.progress_done, job.progress_total) == (3, 10)

    finished = make_job(status=ExportJobStatus.SUCCEEDED)
    export_worker._progress(finished, 5, 5)  # noqa: SLF001
    job = _load(finished)
    assert (job.progress_done, job.progress_total) == (0, 0)


def test_progress_ignores_missing_job() -> None:
    # 任务行被删（学校停用清理等）时不能让线程崩掉
    export_worker._progress(uuid.uuid4(), 1, 1)  # noqa: SLF001


def test_finish_failed_records_error_and_truncates(make_job: Any) -> None:
    job_id = make_job(status=ExportJobStatus.RUNNING)
    export_worker._finish_failed(  # noqa: SLF001
        job_id,
        error="x" * 600,
        included=4,
        missing=2,
        total=6,
    )
    job = _load(job_id)
    assert job.status == ExportJobStatus.FAILED
    assert job.error is not None
    assert len(job.error) == 512
    assert (job.included_count, job.missing_count) == (4, 2)
    assert job.progress_done == 6
    assert job.finished_at is not None


def test_finish_failed_ignores_missing_job() -> None:
    export_worker._finish_failed(  # noqa: SLF001
        uuid.uuid4(), error="boom", included=0, missing=0, total=0
    )


def test_finish_ok_sets_expiry_from_ttl(make_job: Any) -> None:
    job_id = make_job(status=ExportJobStatus.RUNNING)
    export_worker._finish_ok(  # noqa: SLF001
        job_id,
        included=5,
        missing=1,
        total=6,
        artifact="abc.zip",
        byte_size=1024,
    )
    job = _load(job_id)
    assert job.status == ExportJobStatus.SUCCEEDED
    assert job.artifact_relpath == "abc.zip"
    assert job.byte_size == 1024
    assert job.error is None
    assert job.expires_at is not None
    expected = datetime.now(UTC) + timedelta(days=settings.EXPORT_TTL_DAYS)
    assert abs((job.expires_at - expected).total_seconds()) < 60


def test_finish_ok_ignores_non_running(make_job: Any) -> None:
    job_id = make_job(status=ExportJobStatus.FAILED)
    export_worker._finish_ok(  # noqa: SLF001
        job_id, included=1, missing=0, total=1, artifact="x.zip", byte_size=1
    )
    assert _load(job_id).status == ExportJobStatus.FAILED


def test_expire_due_exports_removes_artifact(
    make_job: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    artifact = tmp_path / "old.zip"
    artifact.write_bytes(b"zip-bytes")
    job_id = make_job(
        status=ExportJobStatus.SUCCEEDED,
        artifact_relpath="old.zip",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    with Session(_engine()) as session:
        expired = export_worker.expire_due_exports(session)
    assert expired >= 1
    job = _load(job_id)
    assert job.status == ExportJobStatus.EXPIRED
    assert job.artifact_relpath is None
    assert not artifact.exists()


def test_expire_due_exports_is_noop_when_nothing_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", "/tmp/nonexistent-export-dir")
    with Session(_engine()) as session:
        assert export_worker.expire_due_exports(session) == 0


def test_delete_artifact_tolerates_none_and_missing(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    export_worker.delete_artifact(None)
    export_worker.delete_artifact("gone.zip")
    existing = tmp_path / "here.zip"
    existing.write_bytes(b"x")
    export_worker.delete_artifact("here.zip")
    assert not existing.exists()


def test_startup_recovery_requeues_running(
    make_job: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = make_job(status=ExportJobStatus.RUNNING)
    submitted: list[uuid.UUID] = []
    monkeypatch.setattr(
        export_worker, "submit_export_job", lambda jid: submitted.append(jid)
    )

    export_worker.startup_recovery()

    assert _load(job_id).status == ExportJobStatus.QUEUED
    assert job_id in submitted


def test_run_rebinds_tenant_of_the_job(
    make_job: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 多租户 C3：领取查询不设上下文，执行前必须按任务行重绑，否则 RLS 全拦
    from app.core.tenant_context import current_tenant_id

    job_id = make_job()
    seen: list[uuid.UUID | None] = []
    monkeypatch.setattr(
        export_worker,
        "process_export_job",
        lambda jid: seen.append(current_tenant_id()),
    )
    export_worker._run(job_id)  # noqa: SLF001

    assert seen == [DEFAULT_TENANT_ID]


def test_run_without_job_row_uses_no_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    # 任务行已被删（学校停用清理）：不绑租户，交给 process 空转
    from app.core.tenant_context import current_tenant_id

    seen: list[uuid.UUID | None] = []
    monkeypatch.setattr(
        export_worker,
        "process_export_job",
        lambda jid: seen.append(current_tenant_id()),
    )
    export_worker._run(uuid.uuid4())  # noqa: SLF001
    assert seen == [None]


@pytest.mark.parametrize(
    ("kind", "expected_call"),
    [
        (ExportKind.STUDENT_REPORT_PDF, "student"),
        (ExportKind.CLASS_REPORT_PDF, "class"),
    ],
)
def test_process_routes_pdf_kinds_without_querying_audio(
    make_job: Any,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_call: str,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        export_worker,
        "_process_student_report",
        lambda jid, filt, uid: calls.append("student"),
    )
    monkeypatch.setattr(
        export_worker,
        "_process_class_report",
        lambda jid, filt, uid: calls.append("class"),
    )
    monkeypatch.setattr(
        export_worker,
        "query_candidates",
        lambda session, filt: pytest.fail("PDF 导出不该查音频候选"),
    )

    job_id = make_job(kind=kind)
    export_worker.process_export_job(job_id)
    assert calls == [expected_call]


def test_process_returns_early_when_job_already_claimed(
    make_job: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[uuid.UUID] = []
    monkeypatch.setattr(
        export_worker, "_process_student_report", lambda *a: called.append(a[0])
    )
    job_id = make_job(
        status=ExportJobStatus.RUNNING, kind=ExportKind.STUDENT_REPORT_PDF
    )

    export_worker.process_export_job(job_id)

    assert called == []
    assert _load(job_id).status == ExportJobStatus.RUNNING


def test_process_rejects_oversized_export(
    make_job: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(export_worker, "query_candidates", lambda session, filt: [])
    monkeypatch.setattr(
        export_worker, "present_nbytes", lambda cands: settings.EXPORT_MAX_BYTES + 1
    )
    job_id = make_job()

    export_worker.process_export_job(job_id)

    job = _load(job_id)
    assert job.status == ExportJobStatus.FAILED
    assert job.error == "export_too_large"


def test_process_records_builder_exception(
    make_job: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(export_worker, "query_candidates", lambda session, filt: [])
    monkeypatch.setattr(export_worker, "present_nbytes", lambda cands: 0)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(export_worker, "build_zip", boom)
    job_id = make_job()

    export_worker.process_export_job(job_id)

    job = _load(job_id)
    assert job.status == ExportJobStatus.FAILED
    assert job.error is not None
    assert job.error.startswith("export_failed:")
    assert "disk full" in job.error


def test_process_records_builder_result_error(
    make_job: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(export_worker, "query_candidates", lambda session, filt: [])
    monkeypatch.setattr(export_worker, "present_nbytes", lambda cands: 0)
    monkeypatch.setattr(
        export_worker,
        "build_zip",
        lambda *a, **k: SimpleNamespace(
            error="export_all_missing",
            artifact_name=None,
            included=0,
            missing=3,
            byte_size=0,
        ),
    )
    job_id = make_job()

    export_worker.process_export_job(job_id)

    job = _load(job_id)
    assert job.status == ExportJobStatus.FAILED
    assert job.error == "export_all_missing"
    assert job.missing_count == 3


def test_process_marks_success(
    make_job: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(export_worker, "query_candidates", lambda session, filt: [1, 2])
    monkeypatch.setattr(export_worker, "present_nbytes", lambda cands: 2048)

    def fake_build(
        candidates: Any,
        *,
        scope: str,
        group_by_item: bool,
        root_name: str,
        dest: Any,
        on_progress: Any,
    ) -> Any:
        # 打包过程中会回报进度：这里顺带锁住 on_progress -> _progress 的接线
        on_progress(1, 2)
        return SimpleNamespace(
            error=None,
            artifact_name="out.zip",
            included=2,
            missing=0,
            byte_size=2048,
        )

    monkeypatch.setattr(export_worker, "build_zip", fake_build)
    job_id = make_job()

    export_worker.process_export_job(job_id)

    job = _load(job_id)
    assert job.status == ExportJobStatus.SUCCEEDED
    assert job.artifact_relpath == "out.zip"
    assert job.included_count == 2
    assert job.progress_total == 2


def test_submit_dispatches_to_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    done = threading.Event()
    monkeypatch.setattr(export_worker, "_run", lambda job_id: done.set())
    export_worker.submit_export_job(uuid.uuid4())
    assert done.wait(2), "任务应被投进线程池执行"


def test_process_reraised_when_failure_cannot_be_recorded(
    make_job: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(export_worker, "query_candidates", lambda session, filt: [])
    monkeypatch.setattr(export_worker, "present_nbytes", lambda cands: 0)

    def build_boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk full")

    def finish_boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("db gone too")

    monkeypatch.setattr(export_worker, "build_zip", build_boom)
    monkeypatch.setattr(export_worker, "_finish_failed", finish_boom)
    job_id = make_job()

    # 连失败都记不下来时必须抛出去，让上层日志/重启恢复接手，不能静默
    with pytest.raises(RuntimeError, match="db gone too"):
        export_worker.process_export_job(job_id)


def test_delete_artifact_logs_oserror(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "EXPORT_STORAGE_DIR", str(tmp_path))
    target = tmp_path / "locked.zip"
    target.write_bytes(b"x")

    def boom(self: Any, missing_ok: bool = False) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "unlink", boom)
    with caplog.at_level("ERROR"):
        export_worker.delete_artifact("locked.zip")
    # 删不掉只记日志，不能让到期清理整体失败
    assert "failed to delete export artifact" in caplog.text


def test_sweep_loop_survives_iteration_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import threading
    import time

    def boom(session: Any) -> int:
        raise RuntimeError("db gone")

    monkeypatch.setattr(export_worker, "expire_due_exports", boom)
    monkeypatch.setattr(export_worker, "SWEEP_INTERVAL_S", 0.01)
    stop = threading.Event()
    thread = threading.Thread(
        target=export_worker._sweep_loop,
        args=(stop,),  # noqa: SLF001
    )
    thread.start()
    with caplog.at_level("ERROR"):
        time.sleep(0.05)
        stop.set()
        thread.join(timeout=2)
    assert "export sweeper iteration failed" in caplog.text


def test_start_sweeper_is_idempotent_and_stoppable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    monkeypatch.setattr(export_worker, "expire_due_exports", lambda session: 0)
    monkeypatch.setattr(export_worker, "SWEEP_INTERVAL_S", 0.05)
    try:
        export_worker.start_sweeper()
        first = export_worker._sweeper_thread  # noqa: SLF001
        export_worker.start_sweeper()
        assert export_worker._sweeper_thread is first  # noqa: SLF001
    finally:
        export_worker.stop_sweeper()
    time.sleep(0.1)
    assert export_worker._sweeper_thread is None  # noqa: SLF001
