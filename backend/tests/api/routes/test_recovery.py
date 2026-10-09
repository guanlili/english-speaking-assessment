"""录音上传与异步评分的失败恢复测试（Task 3）。

验收用 mock：断网后重传、重复提交、评分中断恢复、重试上限、XP 不重复结算。
不调用真实付费评分引擎。

账号制：学生 = 学号登录 JWT，上传请求带 Authorization 头（form 不再含
student_id/token）。
"""

import uuid
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_scoring_submitter
from app.core.config import settings
from app.main import app
from app.models import (
    MAX_SCORING_RETRIES,
    Attempt,
    AttemptStatus,
    Student,
)
from app.scoring import worker
from app.scoring.base import ScoringError
from tests.utils.audio import wav_upload, wav_bytes
from tests.utils.credential import make_student


@pytest.fixture(autouse=True)
def cleanup_demo_students(db: Session) -> Generator[None]:
    """本文件测试都往 DEMO01 加入「恢复测试」学生，测完连同作答、账号一并清理，
    避免污染后续 vocab_trail 等对 DEMO01 计数敏感的测试。"""
    yield
    from app.models import PracticeSession, StudentBadge, User

    students = db.exec(
        select(Student).where(
            Student.display_name == "恢复测试"  # type: ignore[arg-type]
        )
    ).all()
    user_ids = [s.user_id for s in students if s.user_id is not None]
    for student in students:
        for model in (Attempt, PracticeSession, StudentBadge):
            for row in db.exec(
                select(model).where(model.student_id == student.id)  # type: ignore[attr-defined]
            ).all():
                db.delete(row)
        db.delete(student)
    for uid in user_ids:
        db.delete(db.get_one(User, uid))
    db.commit()


@pytest.fixture(autouse=True)
def _clear_resubmit_bookkeeping() -> Generator[None]:
    """worker 的重投簿记是模块级状态：测试间必须清空，防止泄漏放大。"""
    yield
    with worker._resubmit_lock:
        worker._resubmit_pending.clear()


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[Callable[[dict[str, str]], None]]:
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)
        while True:
            with Session(db.get_bind()) as check:
                attempt = check.get(Attempt, attempt_id)
                if attempt is None or attempt.status != AttemptStatus.QUEUED:
                    break
            with Session(db.get_bind()) as session:
                worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter

    def set_transcripts(transcripts: dict[str, str]) -> None:
        class FakeAsr:
            name = "fake"

            def transcribe(self, audio: bytes, mime_type: str) -> str:
                return transcripts.get(mime_type, "")

        monkeypatch.setattr(worker, "build_asr_provider", lambda: FakeAsr())

    yield set_transcripts
    app.dependency_overrides.pop(get_scoring_submitter, None)


def _join(db: Session, client: TestClient, name: str = "恢复测试") -> Any:
    """建学生账号 + 登录 + 入班 DEMO01，返回 {student, headers, user}。"""
    return make_student(db, client, "DEMO01", name)


def _today(client: TestClient, headers: dict[str, str]) -> Any:
    return client.get("/api/v1/classes/DEMO01/today", headers=headers).json()


def _submit(
    client: TestClient,
    item_type: str,
    item_id: str,
    headers: dict[str, str],
    session_id: str,
    idempotency_key: str | None = None,
) -> Any:
    data: dict[str, Any] = {
        "item_type": item_type,
        "item_id": item_id,
        "duration_s": "6.0",
        "session_id": session_id,
    }
    if idempotency_key:
        data["idempotency_key"] = idempotency_key
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(6.0)},
        data=data,
        headers=headers,
    )
    return resp


def test_idempotent_reupload_returns_same_attempt(
    client: TestClient, inline_scoring: Any, db: Session
) -> None:
    """断网后重传：同幂等键返回同一作答，不重复创建。"""
    inline_scoring({"audio/wav": "hello world"})
    student = _join(db, client)
    plan = _today(client, student["headers"])
    first = plan["items"][0]
    key = str(uuid.uuid4())

    resp1 = _submit(
        client, first["type"], first["id"], student["headers"], plan["session_id"], key
    )
    assert resp1.status_code == 200
    attempt1 = resp1.json()

    resp2 = _submit(
        client, first["type"], first["id"], student["headers"], plan["session_id"], key
    )
    assert resp2.status_code == 200
    attempt2 = resp2.json()

    assert attempt1["id"] == attempt2["id"]


def test_duplicate_submission_no_double_xp(
    client: TestClient, inline_scoring: Any, db: Session
) -> None:
    """重复提交不重复结算 XP。"""
    inline_scoring({"audio/wav": "hello world"})
    student = _join(db, client)
    plan = _today(client, student["headers"])

    # 完成全部 5 题（3 复述 + 2 问答），重复提交第一题两次验证 XP 不翻倍
    for item in plan["items"]:
        _submit(
            client,
            item["type"],
            item["id"],
            student["headers"],
            plan["session_id"],
            str(uuid.uuid4()),
        )
    # 再用已有幂等键重复提交第一题
    first = plan["items"][0]
    first_key = str(uuid.uuid4())
    _submit(
        client,
        first["type"],
        first["id"],
        student["headers"],
        plan["session_id"],
        first_key,
    )
    _submit(
        client,
        first["type"],
        first["id"],
        student["headers"],
        plan["session_id"],
        first_key,
    )

    # 刷新 today 触发结算
    _today(client, student["headers"])
    _today(client, student["headers"])

    # XP 不应因重复提交翻倍
    db_student = db.get(Student, uuid.UUID(student["student"]["id"]))
    assert db_student is not None
    assert db_student.xp > 0
    # 5 题 × 10 XP + 星级 × 5 + 连胜奖励（如有）
    expected_max = 5 * 10 + 3 * 5 + 10
    assert db_student.xp <= expected_max


def test_stale_scoring_recovery(
    client: TestClient,
    inline_scoring: Any,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """评分中断恢复：僵尸 scoring 作答被重排队列并最终完成。

    恢复现在提交后立即投递（批次04）；本测试禁用真实投递，保持
    「恢复 → 重排队列 → 手动评分 → 完成」的确定性验证——立即投递
    行为由 test_recovered_attempt_is_resubmitted_immediately 覆盖。
    """
    monkeypatch.setattr(worker, "submit_attempt_scoring", lambda aid: None)
    inline_scoring({"audio/wav": "hello world"})
    student = _join(db, client)
    plan = _today(client, student["headers"])
    first = plan["items"][0]

    resp = _submit(
        client, first["type"], first["id"], student["headers"], plan["session_id"]
    )
    attempt_id = uuid.UUID(resp.json()["id"])

    # 模拟 worker 崩溃：手动设为 scoring + 旧 claimed_at
    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        attempt.status = AttemptStatus.SCORING
        attempt.claimed_at = datetime.now(UTC) - timedelta(seconds=300)
        session.add(attempt)
        session.commit()

    # 恢复
    with Session(db.get_bind()) as session:
        recovered = worker.recover_stale_attempts(session)
    assert recovered >= 1

    # 重排队列后手动提交评分
    with Session(db.get_bind()) as session:
        worker.process_attempt(session, attempt_id)
        attempt = session.get(Attempt, attempt_id)
    assert attempt is not None
    assert attempt.status == AttemptStatus.DONE


def test_retry_limit_marks_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Session
) -> None:
    """重试上限：超过 MAX_SCORING_RETRIES 后标记 failed。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        worker,
        "build_asr_provider",
        lambda: (_ for _ in ()).throw(ScoringError("引擎不可用")),
    )

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)
        while True:
            with Session(db.get_bind()) as check:
                attempt = check.get(Attempt, attempt_id)
                if attempt is None or attempt.status != AttemptStatus.QUEUED:
                    break
            with Session(db.get_bind()) as session:
                worker.process_attempt(session, attempt_id)

    app.dependency_overrides[get_scoring_submitter] = lambda: run_inline
    try:
        student = _join(db, client)
        plan = _today(client, student["headers"])
        first = plan["items"][0]
        resp = _submit(
            client, first["type"], first["id"], student["headers"], plan["session_id"]
        )
        attempt = resp.json()
        assert attempt["status"] == "failed"
        assert attempt["retry_count"] == MAX_SCORING_RETRIES
    finally:
        app.dependency_overrides.pop(get_scoring_submitter, None)


def test_retry_redispatched_in_production_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db: Session,
) -> None:
    """生产路径回归：线程池评分失败重排队后必须被自动重新投递。

    之前的缺陷：process_attempt 重试分支置回 queued 后无人再投，
    只有进程重启才能救活。本测试走真实 submit_attempt_scoring
    （不覆盖 get_scoring_submitter），引擎第一次调用抛错、第二次成功，
    断言作答最终 DONE 且 retry_count=1（重投发生且只发生一次）。
    """
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    # 线程池 worker 用全局引擎连库；测试里 conftest 只覆写了 get_db，
    # 必须把全局引擎也指到测试库，否则 worker 线程会读到开发库
    monkeypatch.setattr("app.core.db.engine", db.get_bind())

    class FlakyAsr:
        name = "fake"
        calls = 0

        def transcribe(self, audio: bytes, mime_type: str) -> str:
            FlakyAsr.calls += 1
            if FlakyAsr.calls == 1:
                raise ScoringError("引擎瞬时故障")
            return "hello world"

    monkeypatch.setattr(worker, "build_asr_provider", lambda: FlakyAsr())

    try:
        student = _join(db, client)
        plan = _today(client, student["headers"])
        first = plan["items"][0]
        resp = _submit(
            client, first["type"], first["id"], student["headers"], plan["session_id"]
        )
        assert resp.status_code == 200, resp.text
        attempt_id = uuid.UUID(resp.json()["id"])

        # 轮询等待线程池完成「失败 → 重排队 → 重投 → 成功」全链路
        deadline = datetime.now(UTC) + timedelta(seconds=15)
        final: Attempt | None = None
        while datetime.now(UTC) < deadline:
            with Session(db.get_bind()) as check:
                final = check.get(Attempt, attempt_id)
            if final is not None and final.status not in (
                AttemptStatus.QUEUED,
                AttemptStatus.SCORING,
            ):
                break
            import time

            time.sleep(0.05)

        assert final is not None
        assert final.status == AttemptStatus.DONE, (
            f"重投未生效，状态卡在 {final.status}（retry_count={final.retry_count}）"
        )
        assert final.retry_count == 1
        assert FlakyAsr.calls == 2
    finally:
        worker.shutdown_executor()


def test_stale_failed_marks_are_committed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Session
) -> None:
    """僵尸恢复的 FAILED 分支必须落库：全部僵尸都超重试上限时，
    recovered=0 但 FAILED 状态变更依然要 commit（之前永不落库，
    作答会永远卡在 scoring）。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    from app.core.storage import save_audio_file

    student = _join(db, client)
    plan = _today(client, student["headers"])

    with Session(db.get_bind()) as session:
        path = save_audio_file(b"fake", "audio/wav")
        attempt = Attempt(
            item_type="repeat",
            item_id=uuid.uuid4(),
            student_id=uuid.UUID(student["student"]["id"]),
            session_id=uuid.UUID(plan["session_id"]),
            audio_path=str(path),
            duration_s=5.0,
            status=AttemptStatus.SCORING,
            retry_count=MAX_SCORING_RETRIES,  # 已达上限：恢复只能标 failed
            claimed_at=datetime.now(UTC) - timedelta(seconds=300),
        )
        session.add(attempt)
        session.commit()
        attempt_id = attempt.id

    with Session(db.get_bind()) as session:
        recovered = worker.recover_stale_attempts(session)
    assert recovered == 0  # 没有可重排队的

    # 新会话读库验证 FAILED 已持久化（修复前这里仍会是 scoring）
    with Session(db.get_bind()) as check:
        after = check.get(Attempt, attempt_id)
    assert after is not None
    assert after.status == AttemptStatus.FAILED


def test_queue_full_returns_503(
    client: TestClient, inline_scoring: Any, db: Session
) -> None:
    """队列满时返回 503，前端保留录音提示稍后重试。"""
    inline_scoring({"audio/wav": "hello world"})
    student = _join(db, client)
    plan = _today(client, student["headers"])

    # 填满队列（不提交评分，只创建 queued 作答）
    from app.api.routes.attempts import MAX_QUEUE_SIZE
    from app.core.storage import save_audio_file

    with Session(db.get_bind()) as session:
        for _i in range(MAX_QUEUE_SIZE):
            path = save_audio_file(b"fake", "audio/webm")
            a = Attempt(
                item_type="repeat",
                item_id=uuid.uuid4(),
                student_id=uuid.UUID(student["student"]["id"]),
                session_id=uuid.UUID(plan["session_id"]),
                audio_path=str(path),
                duration_s=5.0,
                status=AttemptStatus.QUEUED,
            )
            session.add(a)
        session.commit()

    # 队列已满 → 503
    first = plan["items"][0]
    resp = _submit(
        client, first["type"], first["id"], student["headers"], plan["session_id"]
    )
    assert resp.status_code == 503
    assert "繁忙" in resp.json()["detail"]


def test_startup_recovery_resubmits_queued_without_stale_scoring(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Session
) -> None:
    """启动恢复无条件重投所有 QUEUED：旧逻辑只在存在僵尸 SCORING 时才重投，
    「落库后、线程领取前进程崩溃」的作答重启后无人再投，永久占坑直到
    队列攒满 200 条触发全站 503。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    from app.core.storage import save_audio_file

    student = _join(db, client)
    plan = _today(client, student["headers"])
    with Session(db.get_bind()) as session:
        path = save_audio_file(b"fake", "audio/wav")
        for _ in range(2):
            session.add(
                Attempt(
                    item_type="repeat",
                    item_id=uuid.uuid4(),
                    student_id=uuid.UUID(student["student"]["id"]),
                    session_id=uuid.UUID(plan["session_id"]),
                    audio_path=str(path),
                    duration_s=5.0,
                    status=AttemptStatus.QUEUED,
                )
            )
        session.commit()

    submitted: list[uuid.UUID] = []
    monkeypatch.setattr(
        worker, "submit_attempt_scoring", lambda aid: submitted.append(aid)
    )
    worker.startup_recovery()
    assert len(submitted) == 2  # 没有任何僵尸 SCORING，QUEUED 仍被重投


def test_stale_recovery_does_not_burn_retry_quota(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Session
) -> None:
    """僵尸恢复不消耗 retry_count：重启/部署是进程级事件，
    不该把在评作答推向重试上限（否则连续两次部署期间在评的会变 FAILED）。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    from app.core.storage import save_audio_file

    student = _join(db, client)
    plan = _today(client, student["headers"])
    with Session(db.get_bind()) as session:
        path = save_audio_file(b"fake", "audio/wav")
        attempt = Attempt(
            item_type="repeat",
            item_id=uuid.uuid4(),
            student_id=uuid.UUID(student["student"]["id"]),
            session_id=uuid.UUID(plan["session_id"]),
            audio_path=str(path),
            duration_s=5.0,
            status=AttemptStatus.SCORING,
            retry_count=1,
            claimed_at=datetime.now(UTC) - timedelta(seconds=300),
        )
        session.add(attempt)
        session.commit()
        attempt_id = attempt.id

    with Session(db.get_bind()) as session:
        recovered = worker.recover_stale_attempts(session)
    assert recovered == 1
    with Session(db.get_bind()) as check:
        after = check.get(Attempt, attempt_id)
    assert after is not None
    assert after.status == AttemptStatus.QUEUED
    assert after.retry_count == 1  # 恢复不再 +1


# ── 队列恢复与租约（wise-quarry-trout 批次04）────────────────────────


def _make_queued_attempt(db: Session, tmp_path: Path, transcript: str | None = None) -> uuid.UUID:
    """直建一条 queued 作答（item_snapshot 带参考文本走跟读评分路径）。"""
    audio = tmp_path / f"{uuid.uuid4()}.wav"
    audio.write_bytes(wav_bytes(5.0))
    attempt = Attempt(
        item_type="repeat",
        item_id=uuid.uuid4(),
        audio_path=str(audio),
        audio_mime="audio/wav",
        duration_s=5.0,
        status=AttemptStatus.QUEUED,
        transcript=transcript,
        item_snapshot={
            "type": "repeat",
            "id": str(uuid.uuid4()),
            "text": "hello world",
            "suggested_seconds": 20,
        },
    )
    db.add(attempt)
    db.commit()
    return attempt.id


def test_recovered_attempt_is_resubmitted_immediately(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """僵尸恢复提交成功即投递：不再等「创建超过 30 分钟」的孤儿规则。"""
    attempt_id = _make_queued_attempt(db, tmp_path)
    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        attempt.status = AttemptStatus.SCORING
        attempt.claimed_at = datetime.now(UTC) - timedelta(seconds=300)
        session.add(attempt)
        session.commit()

    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(
        worker, "submit_attempt_scoring", lambda aid: dispatched.append(aid)
    )
    with Session(db.get_bind()) as session:
        recovered = worker.recover_stale_attempts(session)
    assert recovered == 1
    assert dispatched == [attempt_id]
    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.status == AttemptStatus.QUEUED
    with worker._resubmit_lock:
        assert attempt_id in worker._resubmit_pending


def test_resubmit_pending_retried_by_sweep(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """恢复后投递失败：候选留簿记，下一轮清扫继续重试，直到离开 queued。"""
    attempt_id = _make_queued_attempt(db, tmp_path)
    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        attempt.status = AttemptStatus.SCORING
        attempt.claimed_at = datetime.now(UTC) - timedelta(seconds=300)
        session.add(attempt)
        session.commit()

    calls: list[uuid.UUID] = []

    def flaky_submit(aid: uuid.UUID) -> None:
        calls.append(aid)
        if len(calls) == 1:
            raise RuntimeError("executor rejected")

    monkeypatch.setattr(worker, "submit_attempt_scoring", flaky_submit)
    with Session(db.get_bind()) as session:
        assert worker.recover_stale_attempts(session) == 1
    assert len(calls) == 1  # 第一次投递被拒
    with worker._resubmit_lock:
        assert attempt_id in worker._resubmit_pending

    with Session(db.get_bind()) as session:
        worker.sweep_orphans(session)
    assert len(calls) == 2  # 下一轮清扫重试投递成功

    # 被领取（离开 queued）后，候选从簿记清掉
    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        attempt.status = AttemptStatus.SCORING
        attempt.claimed_at = datetime.now(UTC)
        session.add(attempt)
        session.commit()
    monkeypatch.setattr(worker, "submit_attempt_scoring", lambda aid: calls.append(aid))
    with Session(db.get_bind()) as session:
        worker.sweep_orphans(session)
    with worker._resubmit_lock:
        assert attempt_id not in worker._resubmit_pending


def test_stale_worker_discards_result_after_reclaim(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """慢旧 worker 被回收重领后不得改写新结果（租约 = 领取时刻代次）。"""
    import threading

    attempt_id = _make_queued_attempt(db, tmp_path)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    class GatedAsr:
        name = "mock"
        calls = 0

        def transcribe(self, audio: bytes, mime_type: str) -> str:
            GatedAsr.calls += 1
            if GatedAsr.calls == 1:
                entered.set()
                assert release.wait(timeout=5), "测试同步点超时"
                return "stale transcript"
            return "fresh transcript"

    gate = GatedAsr()
    monkeypatch.setattr(worker, "build_asr_provider", lambda: gate)
    monkeypatch.setattr(worker, "submit_attempt_scoring", lambda aid: None)

    result: dict[str, object] = {}

    def old_worker() -> None:
        try:
            with Session(db.get_bind()) as session:
                worker.process_attempt(session, attempt_id)
            result["old"] = "finished"
        except Exception as exc:  # noqa: BLE001 - 记录旧线程任何异常
            result["old"] = repr(exc)

    thread = threading.Thread(target=old_worker)
    thread.start()
    assert entered.wait(timeout=5), "旧 worker 未进入 ASR"

    # 旧 worker 卡在外部调用期间被回收 → 重领 → 新 worker 完成（fresh）
    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.status == AttemptStatus.SCORING
        attempt.claimed_at = datetime.now(UTC) - timedelta(seconds=300)
        session.add(attempt)
        session.commit()
        worker.recover_stale_attempts(session)
    with Session(db.get_bind()) as session:
        worker.process_attempt(session, attempt_id)

    release.set()
    thread.join(timeout=5)

    with Session(db.get_bind()) as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        assert attempt.status == AttemptStatus.DONE
        assert attempt.transcript == "fresh transcript"
        assert attempt.retry_count == 0  # 旧结果被丢弃，不写失败也不烧重试


def test_detail_pending_timeout_uses_detail_start(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """详情挂起超时按 pending_since 判定：长排队后刚进入 rubric 不被误杀。"""
    from datetime import UTC as _UTC

    now = datetime.now(_UTC)

    def _done_attempt(**rubric: object) -> Attempt:
        row = Attempt(
            item_type="question",
            item_id=uuid.uuid4(),
            audio_path="/tmp/x.wav",
            audio_mime="audio/wav",
            duration_s=5.0,
            status=AttemptStatus.DONE,
            rubric=dict(rubric) if rubric else None,
            created_at=now - timedelta(minutes=10),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    fresh = _done_attempt(
        status="pending", pending_since=(now).isoformat()
    )
    stale = _done_attempt(
        status="pending", pending_since=(now - timedelta(seconds=121)).isoformat()
    )
    legacy = _done_attempt(status="pending")
    monkeypatch.setattr(worker, "submit_attempt_scoring", lambda aid: None)
    with Session(db.get_bind()) as session:
        worker.sweep_orphans(session)

    db.refresh(fresh)
    db.refresh(stale)
    db.refresh(legacy)
    # 刚进入详情阶段：保持 pending（旧口径按 created_at 会误杀）
    assert fresh.rubric is not None and fresh.rubric.get("status") == "pending"
    # 详情阶段超时：关闭为 unavailable
    assert stale.rubric == {"status": "unavailable"}
    # 历史行无 pending_since：沿用创建时间口径
    assert legacy.rubric == {"status": "unavailable"}


def test_complete_detail_first_writer_wins(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重复投递的 detail 线程：先写者胜，迟到结果不得覆盖。"""
    attempt = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        audio_path="/tmp/x.wav",
        audio_mime="audio/wav",
        duration_s=5.0,
        status=AttemptStatus.DONE,
        transcript="hello",
        rubric={"status": "pending"},
    )
    db.add(attempt)
    db.commit()
    try:
        results = iter([{"mock_score": 1}, {"mock_score": 2}])
        monkeypatch.setattr(worker, "_score_rubric", lambda *a: next(results))
        worker._complete_detail(attempt.id, "q", "B1", "hello")
        db.refresh(attempt)
        assert attempt.rubric == {"mock_score": 1}
        worker._complete_detail(attempt.id, "q", "B1", "hello")
        db.refresh(attempt)
        assert attempt.rubric == {"mock_score": 1}  # 迟到结果不覆盖
    finally:
        db.delete(attempt)
        db.commit()


def test_shutdown_cancels_retry_timers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """退出时取消在飞重试 Timer：关闭后不得重建线程池。"""
    fired: list[uuid.UUID] = []
    monkeypatch.setattr(
        worker, "submit_attempt_scoring", lambda aid: fired.append(aid)
    )
    worker._schedule_retry(uuid.uuid4(), 60.0)
    with worker._retry_timers_lock:
        timers = list(worker._retry_timers)
    assert len(timers) == 1
    worker.shutdown_executor()
    timers[0].join(timeout=1)
    assert not timers[0].is_alive()
    assert fired == []  # 已取消，从未点火重建线程池
    with worker._retry_timers_lock:
        assert not worker._retry_timers
