"""录音上传与异步评分的失败恢复测试（Task 3）。

验收用 mock：断网后重传、重复提交、评分中断恢复、重试上限、XP 不重复结算。
不调用真实付费评分引擎。
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


@pytest.fixture(autouse=True)
def cleanup_demo_students(db: Session) -> Generator[None]:
    """本文件测试都往 DEMO01 加入「恢复测试」学生，测完连同作答一并清理，
    避免污染后续 vocab_trail 等对 DEMO01 计数敏感的测试。"""
    yield
    from app.models import PracticeSession, StudentBadge

    students = db.exec(
        select(Student).where(
            Student.display_name == "恢复测试"  # type: ignore[arg-type]
        )
    ).all()
    for student in students:
        for model in (Attempt, PracticeSession, StudentBadge):
            for row in db.exec(
                select(model).where(model.student_id == student.id)  # type: ignore[attr-defined]
            ).all():
                db.delete(row)
        db.delete(student)
    db.commit()


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


def _join(client: TestClient, name: str = "恢复测试") -> Any:
    resp = client.post(
        "/api/v1/classes/DEMO01/join", json={"display_name": name}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _today(client: TestClient, student_id: str) -> Any:
    return client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": student_id}
    ).json()


def _submit(
    client: TestClient,
    item_type: str,
    item_id: str,
    student_id: str,
    session_id: str,
    idempotency_key: str | None = None,
) -> Any:
    data: dict[str, Any] = {
        "item_type": item_type,
        "item_id": item_id,
        "duration_s": "6.0",
        "student_id": student_id,
        "session_id": session_id,
    }
    if idempotency_key:
        data["idempotency_key"] = idempotency_key
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"bytes", "audio/webm")},
        data=data,
    )
    return resp


def test_idempotent_reupload_returns_same_attempt(
    client: TestClient, inline_scoring: Any
) -> None:
    """断网后重传：同幂等键返回同一作答，不重复创建。"""
    inline_scoring({"audio/webm": "hello world"})
    student = _join(client)
    plan = _today(client, student["id"])
    first = plan["items"][0]
    key = str(uuid.uuid4())

    resp1 = _submit(
        client, first["type"], first["id"], student["id"], plan["session_id"], key
    )
    assert resp1.status_code == 200
    attempt1 = resp1.json()

    resp2 = _submit(
        client, first["type"], first["id"], student["id"], plan["session_id"], key
    )
    assert resp2.status_code == 200
    attempt2 = resp2.json()

    assert attempt1["id"] == attempt2["id"]


def test_duplicate_submission_no_double_xp(
    client: TestClient, inline_scoring: Any, db: Session
) -> None:
    """重复提交不重复结算 XP。"""
    inline_scoring({"audio/webm": "hello world"})
    student = _join(client)
    plan = _today(client, student["id"])

    # 完成全部 5 题（3 复述 + 2 问答），重复提交第一题两次验证 XP 不翻倍
    for item in plan["items"]:
        _submit(
            client, item["type"], item["id"], student["id"], plan["session_id"], str(uuid.uuid4())
        )
    # 再用已有幂等键重复提交第一题
    first = plan["items"][0]
    first_key = str(uuid.uuid4())
    _submit(
        client, first["type"], first["id"], student["id"], plan["session_id"], first_key
    )
    _submit(
        client, first["type"], first["id"], student["id"], plan["session_id"], first_key
    )

    # 刷新 today 触发结算
    _today(client, student["id"])
    _today(client, student["id"])

    # XP 不应因重复提交翻倍
    db_student = db.get(Student, uuid.UUID(student["id"]))
    assert db_student is not None
    assert db_student.xp > 0
    # 5 题 × 10 XP + 星级 × 5 + 连胜奖励（如有）
    expected_max = 5 * 10 + 3 * 5 + 10
    assert db_student.xp <= expected_max


def test_stale_scoring_recovery(
    client: TestClient, inline_scoring: Any, db: Session
) -> None:
    """评分中断恢复：僵尸 scoring 作答被重排队列并最终完成。"""
    inline_scoring({"audio/webm": "hello world"})
    student = _join(client)
    plan = _today(client, student["id"])
    first = plan["items"][0]

    resp = _submit(
        client, first["type"], first["id"], student["id"], plan["session_id"]
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
        student = _join(client)
        plan = _today(client, student["id"])
        first = plan["items"][0]
        resp = _submit(
            client, first["type"], first["id"], student["id"], plan["session_id"]
        )
        attempt = resp.json()
        assert attempt["status"] == "failed"
        assert attempt["retry_count"] == MAX_SCORING_RETRIES
    finally:
        app.dependency_overrides.pop(get_scoring_submitter, None)


def test_queue_full_returns_503(
    client: TestClient, inline_scoring: Any, db: Session
) -> None:
    """队列满时返回 503，前端保留录音提示稍后重试。"""
    inline_scoring({"audio/webm": "hello world"})
    student = _join(client)
    plan = _today(client, student["id"])

    # 填满队列（不提交评分，只创建 queued 作答）
    from app.api.routes.attempts import MAX_QUEUE_SIZE
    from app.core.storage import save_audio_file

    with Session(db.get_bind()) as session:
        for _i in range(MAX_QUEUE_SIZE):
            path = save_audio_file(b"fake", "audio/webm")
            a = Attempt(
                item_type="repeat",
                item_id=uuid.uuid4(),
                student_id=uuid.UUID(student["id"]),
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
        client, first["type"], first["id"], student["id"], plan["session_id"]
    )
    assert resp.status_code == 503
    assert "繁忙" in resp.json()["detail"]
