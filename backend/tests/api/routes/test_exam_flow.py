"""Automated phases use fixed server clocks and explicit playback/Next events."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session

from app.models import (
    Classroom,
    ClassroomExercise,
    ExamItemSettings,
    Passage,
    PracticeSession,
)
from app.services import exam, exam_flow
from tests.api.routes.test_exam import _cleanup_classroom, _resp_json, _today
from tests.utils.credential import make_student


def test_automated_exam_phases_and_resume(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    ids = [uuid.uuid4() for _ in range(4)]
    passage = Passage(
        id=ids[1],
        slug=f"flow-{ids[1]}",
        title="Read",
        text="Read this.",
        cefr_band="B1",
    )
    db.add(passage)
    db.commit()
    settings = ExamItemSettings(
        wait_seconds=3, after_audio_seconds=2, prep_seconds=7
    ).model_dump()
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        is_exam=True,
        time_limit_minutes=5,
        snapshot_items=[
            {
                "id": str(item_id),
                "type": kind,
                "text": "Read this instruction.",
                "suggested_seconds": 10,
                "exam_flow": settings,
            }
            for item_id, kind in zip(
                ids, ["instruction", "passage", "repeat", "question"], strict=True
            )
        ],
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    monkeypatch.setattr(exam, "_now", lambda: now)
    try:
        plan = _today(client, made["headers"], code)
        sid = plan["session_id"]

        def event(index: int, name: str) -> Response:
            return client.post(
                f"/api/v1/classes/{code}/exam/flow",
                json={"session_id": sid, "item_id": str(ids[index]), "event": name},
                headers=made["headers"],
            )

        def phase() -> dict[str, object]:
            return _today(client, made["headers"], code)["exam"]

        response = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": sid},
            headers=made["headers"],
        )
        assert response.status_code == 200
        assert phase()["phase"] == "waiting"
        assert event(0, "next").status_code == 422
        assert event(0, "audio-ended").status_code == 422
        now += timedelta(seconds=4)
        assert phase()["phase"] == "audio"
        assert event(0, "next").status_code == 422
        now += timedelta(seconds=20)
        assert phase()["phase"] == "audio"  # No guessed audio duration.
        assert event(0, "audio-ended").status_code == 200
        assert phase()["phase"] == "ready"
        assert event(0, "next").status_code == 200
        assert event(0, "next").status_code == 200  # Retry cannot reset the next item.
        assert phase()["phase"] == "waiting"
        now += timedelta(seconds=5)
        assert phase()["phase"] == "answering"
        assert phase()["item_remaining_seconds"] == 8
        assert event(1, "next").status_code == 422
        now += timedelta(seconds=10)
        assert phase()["phase"] == "ready"
        assert phase()["current_item_index"] == 1
        assert event(1, "next").status_code == 200
        now += timedelta(seconds=3)
        assert phase()["phase"] == "audio"
        assert event(2, "audio-ended").status_code == 200
        assert phase()["phase"] == "buffer"
        now += timedelta(seconds=2)
        assert phase()["phase"] == "answering"
        now += timedelta(seconds=10)
        assert event(2, "next").status_code == 200
        now += timedelta(seconds=3)
        assert event(3, "audio-ended").status_code == 200
        assert phase()["phase"] == "preparing"
        now += timedelta(seconds=8)
        assert phase()["phase"] == "buffer"
        now += timedelta(seconds=1)
        assert phase()["phase"] == "answering"
        now += timedelta(seconds=10)
        assert event(3, "next").status_code == 200
        assert phase()["ended"] is True
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(passage)
        db.commit()


def test_global_deadline_is_read_only_even_during_audio(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    exercise = ClassroomExercise(
        classroom_id=uuid.uuid4(),
        is_exam=True,
        time_limit_minutes=5,
        snapshot_items=[
            {
                "id": str(uuid.uuid4()),
                "type": "repeat",
                "text": "Listen.",
                "suggested_seconds": 360,
                "exam_flow": ExamItemSettings().model_dump(),
            }
        ],
    )
    ps = PracticeSession(
        classroom_id=exercise.classroom_id,
        student_id=uuid.uuid4(),
        passage_id=uuid.uuid4(),
        band="B1",
        session_date=date.today(),
        exam_started_at=now,
    )
    assert exam_flow.status(ps, exercise, now + timedelta(seconds=301)).ended
    assert exam_flow.ended(ps, exercise, now + timedelta(seconds=301))
    monkeypatch.setattr(exam, "_now", lambda: now + timedelta(seconds=301))
    assert not exam.exam_feedback_locked(db, ps, exercise)
    assert ps.exam_ended_at is None


def test_question_settings_are_snapshotted(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    passage = Passage(
        slug=f"flow-{uuid.uuid4()}", title="Read", text="Read this.", cefr_band="B1"
    )
    db.add(passage)
    db.commit()
    code = classroom["code"]
    endpoint = f"/api/v1/admin/exam-items/passage/{passage.id}/settings"
    try:
        assert (
            client.put(
                endpoint, json={"wait_seconds": -1}, headers=superuser_token_headers
            ).status_code
            == 422
        )
        assert (
            client.put(
                endpoint, json={"wait_seconds": 8}, headers=superuser_token_headers
            ).status_code
            == 200
        )
        response = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={
                "items": [{"type": "passage", "id": str(passage.id)}],
                "is_exam": True,
                "automated_exam": True,
                "time_limit_minutes": 5,
            },
            headers=superuser_token_headers,
        )
        assert response.status_code == 200, response.text
        row = db.get(Classroom, uuid.UUID(classroom["id"]))
        assert row is not None
        db.refresh(row)
        exercise = db.get(ClassroomExercise, row.current_exercise_id)
        assert exercise is not None
        flow = cast(dict[str, object], exercise.snapshot_items[0]["exam_flow"])
        assert flow["wait_seconds"] == 8
        assert (
            client.put(
                endpoint, json={"wait_seconds": 1}, headers=superuser_token_headers
            ).status_code
            == 200
        )
        db.refresh(exercise)
        assert exercise is not None
        flow = cast(dict[str, object], exercise.snapshot_items[0]["exam_flow"])
        assert flow["wait_seconds"] == 8
        made = make_student(db, client, code)
        assert client.get(endpoint, headers=made["headers"]).status_code == 403
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(passage)
        db.commit()


def test_retained_recording_upload_window(db: Session) -> None:
    from fastapi import HTTPException

    now = datetime.now(UTC)
    ids = [uuid.uuid4(), uuid.uuid4()]
    exercise = ClassroomExercise(
        classroom_id=uuid.uuid4(),
        is_exam=True,
        time_limit_minutes=5,
        snapshot_items=[
            {
                "id": str(item_id),
                "type": "passage",
                "text": "Read.",
                "suggested_seconds": 5,
                "exam_flow": ExamItemSettings(wait_seconds=0).model_dump(),
            }
            for item_id in ids
        ],
    )
    ps = PracticeSession(
        classroom_id=exercise.classroom_id,
        student_id=uuid.uuid4(),
        passage_id=ids[0],
        band="B1",
        session_date=date.today(),
        exam_started_at=now,
    )
    # Resuming the same finished item preserves the unsubmitted recording.
    exam_flow.require_submission(
        db, ps, exercise, "passage", ids[0], now + timedelta(seconds=60), 15
    )
    ps.exam_flow_state = {
        "0": {
            "started_at": now.isoformat(),
            "next_at": (now + timedelta(seconds=60)).isoformat(),
        },
        "1": {"started_at": (now + timedelta(seconds=60)).isoformat()},
    }
    exam_flow.require_submission(
        db, ps, exercise, "passage", ids[0], now + timedelta(seconds=74), 15
    )
    with pytest.raises(HTTPException):
        exam_flow.require_submission(
            db, ps, exercise, "passage", ids[0], now + timedelta(seconds=76), 15
        )


def test_last_item_next_keeps_upload_grace_through_attempts_gate(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """末题 Next 落 exam_ended_at 后，15 秒补传窗口必须穿过 /attempts 完整门禁。"""
    from tests.utils.audio import wav_upload

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    item_id = uuid.uuid4()
    passage = Passage(
        id=item_id,
        slug=f"flow-grace-{item_id}",
        title="Read",
        text="Read this.",
        cefr_band="B1",
    )
    db.add(passage)
    db.commit()
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        is_exam=True,
        time_limit_minutes=5,
        snapshot_items=[
            {
                "id": str(item_id),
                "type": "passage",
                "text": "Read this.",
                "suggested_seconds": 5,
                "exam_flow": ExamItemSettings(wait_seconds=0).model_dump(),
            }
        ],
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    monkeypatch.setattr(exam, "_now", lambda: now)

    def upload(key: str) -> Response:
        return client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(6.0)},
            data={
                "item_type": "passage",
                "item_id": str(item_id),
                "duration_s": "6.0",
                "session_id": sid,
                "idempotency_key": key,
            },
            headers=made["headers"],
        )

    try:
        sid = _today(client, made["headers"], code)["session_id"]
        assert (
            client.post(
                f"/api/v1/classes/{code}/exam/start",
                json={"session_id": sid},
                headers=made["headers"],
            ).status_code
            == 200
        )
        now += timedelta(seconds=10)
        assert (
            client.post(
                f"/api/v1/classes/{code}/exam/flow",
                json={
                    "session_id": sid,
                    "item_id": str(item_id),
                    "event": "next",
                },
                headers=made["headers"],
            ).status_code
            == 200
        )
        # 末题 Next 已结束整场（exam_ended_at 落库）：窗口外新键提交被拒，
        # 窗口内（回拨模拟另一标签页的保留录音）首次提交必须放行。
        now += timedelta(seconds=16)
        response = upload("grace-key-late")
        assert response.status_code == 422
        assert response.json()["detail"] == "考试时间已到，已自动交卷"
        now -= timedelta(seconds=15)
        assert upload("grace-key-1").status_code == 200
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(passage)
        db.commit()


def test_whole_deadline_boundary_blocks_first_upload(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整场截止的边界与 ended() 对齐：恰好到点/过点拒绝，临点前放行。"""
    from tests.utils.audio import wav_upload

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    item_id = uuid.uuid4()
    passage = Passage(
        id=item_id,
        slug=f"flow-edge-{item_id}",
        title="Read",
        text="Read this.",
        cefr_band="B1",
    )
    db.add(passage)
    db.commit()
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        is_exam=True,
        time_limit_minutes=5,
        snapshot_items=[
            {
                "id": str(item_id),
                "type": "passage",
                "text": "Read this.",
                "suggested_seconds": 5,
                "exam_flow": ExamItemSettings(wait_seconds=0).model_dump(),
            }
        ],
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    start = datetime.now(UTC)
    monkeypatch.setattr(exam, "_now", lambda: start)

    def upload(key: str) -> Response:
        return client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(6.0)},
            data={
                "item_type": "passage",
                "item_id": str(item_id),
                "duration_s": "6.0",
                "session_id": sid,
                "idempotency_key": key,
            },
            headers=made["headers"],
        )

    try:
        sid = _today(client, made["headers"], code)["session_id"]
        assert (
            client.post(
                f"/api/v1/classes/{code}/exam/start",
                json={"session_id": sid},
                headers=made["headers"],
            ).status_code
            == 200
        )
        deadline = start + timedelta(minutes=5)
        monkeypatch.setattr(exam, "_now", lambda: deadline)
        assert upload("edge-at-deadline").status_code == 422
        monkeypatch.setattr(exam, "_now", lambda: deadline + timedelta(seconds=1))
        assert upload("edge-after-deadline").status_code == 422
        monkeypatch.setattr(exam, "_now", lambda: deadline - timedelta(seconds=1))
        assert upload("edge-before-deadline").status_code == 200
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(passage)
        db.commit()
