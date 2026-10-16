import uuid
from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    PracticeSession,
    Student,
    get_datetime_utc,
)
from tests.utils.audio import wav_upload
from tests.utils.credential import make_student


@pytest.fixture
def teaching_round(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> Generator[dict]:
    headers = superuser_token_headers
    created = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=headers
    ).json()
    code = created["code"]
    classroom = db.get(Classroom, uuid.UUID(created["id"]))
    assert classroom is not None
    students = [
        make_student(db, client, code, name) for name in ("Alice", "Ben", "Other")
    ]
    ids = [uuid.uuid4(), uuid.uuid4()]
    source = ClassroomExercise(
        classroom_id=classroom.id,
        title="Original frozen round",
        snapshot_items=[
            {
                "id": str(ids[0]),
                "type": "repeat",
                "text": "Original frozen sentence.",
                "suggested_seconds": 20,
                "replay_limit": 0,
            },
            {
                "id": str(ids[1]),
                "type": "question",
                "text": "What do you enjoy?",
                "suggested_seconds": 30,
            },
        ],
        status="published",
    )
    db.add(source)
    db.flush()
    classroom.current_exercise_id = source.id
    db.add(classroom)
    db.commit()
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=students[0]["headers"]
    ).json()
    original = db.get(PracticeSession, uuid.UUID(plan["session_id"]))
    assert original is not None
    attempt = Attempt(
        session_id=original.id,
        student_id=original.student_id,
        item_type="repeat",
        item_id=ids[0],
        item_snapshot=source.snapshot_items[0],
        audio_path="unused-feedback-test",
        duration_s=2,
        status="done",
        overall=88,
    )
    db.add(attempt)
    db.commit()
    yield {
        "code": code,
        "classroom": classroom,
        "students": students,
        "source": source,
        "ids": ids,
        "original": original,
        "attempt": attempt,
        "headers": headers,
    }
    db.rollback()
    student_ids = db.exec(
        select(Student.id).where(Student.classroom_id == classroom.id)
    ).all()
    db.exec(delete(Attempt).where(col(Attempt.student_id).in_(student_ids)))  # type: ignore[call-overload]
    db.commit()
    response = client.delete(
        f"/api/v1/classes/{code}?delete_history=true", headers=headers
    )
    assert response.status_code == 200, response.text


def test_teacher_feedback_ownership_revision_and_exam_mask(
    client: TestClient,
    db: Session,
    teaching_round: dict,
    normal_user_token_headers: dict[str, str],
) -> None:
    r = teaching_round
    endpoint = f"/api/v1/attempts/{r['attempt'].id}/teacher-feedback"
    payload = {
        "text": "Use a clear opening sentence.\nThen add one detail.",
        "focus": True,
        "expected_revision": 0,
    }
    assert (
        client.put(
            endpoint, headers=r["students"][0]["headers"], json=payload
        ).status_code
        == 403
    )
    assert (
        client.put(
            endpoint, headers=normal_user_token_headers, json=payload
        ).status_code
        == 403
    )
    saved = client.put(endpoint, headers=r["headers"], json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["teacher_feedback_revision"] == 1
    assert saved.json()["overall"] == 88
    assert client.put(endpoint, headers=r["headers"], json=payload).status_code == 409
    read = f"/api/v1/attempts/{r['attempt'].id}"
    assert client.get(read, headers=r["students"][1]["headers"]).status_code == 403
    assert (
        client.get(read, headers=r["students"][0]["headers"]).json()["teacher_feedback"]
        == payload["text"]
    )
    r["source"].is_exam = True
    r["source"].time_limit_minutes = 30
    r["original"].exam_started_at = get_datetime_utc()
    db.add(r["source"])
    db.add(r["original"])
    db.commit()
    masked = client.get(read, headers=r["students"][0]["headers"]).json()
    assert (
        masked["teacher_feedback"] is None and masked["teacher_feedback_author"] is None
    )
    assert not masked["teacher_focus"] and masked["teacher_feedback_revision"] == 0
    plan = client.get(
        f"/api/v1/classes/{r['code']}/today",
        params={"session_id": str(r["original"].id)},
        headers=r["students"][0]["headers"],
    ).json()
    assert (
        plan["attempts"][0]["teacher_feedback"] is None
        and not plan["attempts"][0]["teacher_focus"]
    )
    assert (
        client.get(read, headers=r["headers"]).json()["teacher_feedback"]
        == payload["text"]
    )
    r["original"].exam_ended_at = get_datetime_utc()
    db.add(r["original"])
    db.commit()
    assert client.get(read, headers=r["students"][0]["headers"]).json()["teacher_focus"]
    cleared = client.put(
        endpoint,
        headers=r["headers"],
        json={"text": "  ", "focus": False, "expected_revision": 1},
    ).json()
    assert cleared["teacher_feedback"] is None and not cleared["teacher_focus"]
    assert cleared["overall"] == 88
    assert (
        client.put(
            endpoint, headers=r["headers"], json={**payload, "text": "x" * 4001}
        ).status_code
        == 422
    )


def test_targeted_followup_is_private_frozen_and_separate(
    client: TestClient,
    db: Session,
    teaching_round: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    # Join responses expose the profile ID directly in the helper.
    recipients = [
        str(
            db.exec(
                select(Student).where(
                    Student.classroom_id == r["classroom"].id,
                    Student.display_name == name,
                )
            )
            .one()
            .id
        )
        for name in ("Alice", "Ben")
    ]
    body = {
        "source_exercise_id": str(r["source"].id),
        "title": "Focus practice",
        "student_ids": recipients,
        "item_ids": [str(r["ids"][0])],
    }
    made = client.post(base + "/followups", headers=r["headers"], json=body)
    assert made.status_code == 200, made.text
    task_id = made.json()["id"]
    assert (
        client.post(
            base + "/followups",
            headers=r["headers"],
            json={**body, "student_ids": [str(uuid.uuid4())]},
        ).status_code
        == 422
    )
    own = client.get(base + "/followups", headers=r["students"][0]["headers"]).json()
    assert len(own) == 1 and len(own[0]["targets"]) == 1
    assert own[0]["targets"][0]["display_name"] == "Alice"
    assert (
        client.get(base + "/followups", headers=r["students"][2]["headers"]).json()
        == []
    )
    assert (
        client.post(
            base + f"/followups/{task_id}/start", headers=r["students"][2]["headers"]
        ).status_code
        == 404
    )
    start = client.post(
        base + f"/followups/{task_id}/start", headers=r["students"][0]["headers"]
    ).json()["session_id"]
    assert (
        client.post(
            base + f"/followups/{task_id}/start", headers=r["students"][0]["headers"]
        ).json()["session_id"]
        == start
    )
    ps = db.get(PracticeSession, uuid.UUID(start))
    assert ps is not None
    ps.session_date -= timedelta(days=1)
    db.add(ps)
    db.commit()
    assert (
        client.post(
            base + f"/followups/{task_id}/start", headers=r["students"][0]["headers"]
        ).json()["session_id"]
        == start
    )
    r["source"].snapshot_items = [
        {**r["source"].snapshot_items[0], "text": "Later changed text"}
    ]
    db.add(r["source"])
    db.commit()
    plan = client.get(
        base + "/today",
        params={"session_id": start},
        headers=r["students"][0]["headers"],
    ).json()
    assert (
        plan["items"][0]["text"] == "Original frozen sentence."
        and len(plan["items"]) == 1
    )
    assert plan["exam"] is None and plan["questions_exhausted"]
    assert (
        client.get(
            base + "/next-question",
            params={"session_id": start},
            headers=r["students"][0]["headers"],
        ).status_code
        == 422
    )
    history = client.get(base + "/exercises", headers=r["headers"]).json()
    assert [row["id"] for row in history] == [str(r["source"].id)]
    db.refresh(r["classroom"])
    db.refresh(r["attempt"])
    assert (
        r["classroom"].current_exercise_id == r["source"].id
        and r["attempt"].overall == 88
    )
    # No live RepeatSentence exists for this ID; submission must use the copied snapshot.
    monkeypatch.setattr(
        "app.scoring.worker.submit_attempt_scoring", lambda *_args, **_kwargs: None
    )
    upload = client.post(
        "/api/v1/attempts",
        headers=r["students"][0]["headers"],
        data={
            "session_id": start,
            "item_id": str(r["ids"][0]),
            "item_type": "repeat",
            "duration_s": "2",
            "idempotency_key": uuid.uuid4().hex,
        },
        files={"audio": wav_upload()},
    )
    assert upload.status_code == 200, upload.text
    saved = db.get(Attempt, uuid.UUID(upload.json()["id"]))
    assert saved is not None
    saved.status = "done"
    db.add(saved)
    db.commit()
    progress = client.get(base + "/followups", headers=r["headers"]).json()[0][
        "targets"
    ]
    assert any(
        row["student_id"] == recipients[0] and row["done_count"] == 1
        for row in progress
    )
    assert (
        client.post(
            base + f"/followups/{task_id}/cancel", headers=r["students"][0]["headers"]
        ).status_code
        == 403
    )
    assert (
        client.post(
            base + f"/followups/{task_id}/cancel", headers=r["headers"]
        ).status_code
        == 200
    )
    assert (
        client.post(
            base + f"/followups/{task_id}/start", headers=r["students"][0]["headers"]
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/attempts",
            headers=r["students"][0]["headers"],
            data={
                "session_id": start,
                "item_id": str(r["ids"][0]),
                "item_type": "repeat",
                "duration_s": "2",
            },
            files={"audio": wav_upload()},
        ).status_code
        == 422
    )


def test_followup_does_not_bypass_active_exams(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    r["source"].is_exam = True
    r["source"].time_limit_minutes = 30
    db.add(r["source"])
    db.commit()
    body = {
        "source_exercise_id": str(r["source"].id),
        "title": "Exam review",
        "student_ids": [str(r["original"].student_id)],
        "item_ids": [str(r["ids"][0])],
    }
    endpoint = f"/api/v1/classes/{r['code']}/followups"
    assert client.post(endpoint, headers=r["headers"], json=body).status_code == 422
    r["classroom"].current_exercise_id = None
    r["source"].status = "archived"
    r["original"].exam_started_at = get_datetime_utc()
    db.add(r["classroom"])
    db.add(r["source"])
    db.add(r["original"])
    db.commit()
    assert client.post(endpoint, headers=r["headers"], json=body).status_code == 422
    r["original"].exam_ended_at = get_datetime_utc()
    db.add(r["original"])
    db.commit()
    assert client.post(endpoint, headers=r["headers"], json=body).status_code == 200


def test_student_filter_applies_before_task_limit(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}/followups"
    body = {
        "source_exercise_id": str(r["source"].id),
        "title": "Alice practice",
        "student_ids": [str(r["original"].student_id)],
        "item_ids": [str(r["ids"][0])],
    }
    first = client.post(base, headers=r["headers"], json=body).json()["id"]
    ben = db.exec(
        select(Student).where(
            Student.classroom_id == r["classroom"].id, Student.display_name == "Ben"
        )
    ).one()
    assert (
        client.post(
            base,
            headers=r["headers"],
            json={**body, "title": "Ben practice", "student_ids": [str(ben.id)]},
        ).status_code
        == 200
    )
    rows = client.get(
        base, params={"limit": 1}, headers=r["students"][0]["headers"]
    ).json()
    assert [row["id"] for row in rows] == [first]


def test_cancellation_during_audio_probe_does_not_accept_or_leave_audio(
    client: TestClient,
    db: Session,
    teaching_round: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from app.api.routes import attempts as api
    from app.core.config import settings

    r = teaching_round
    body = {
        "source_exercise_id": str(r["source"].id),
        "title": "Cancelled during upload",
        "student_ids": [str(r["original"].student_id)],
        "item_ids": [str(r["ids"][0])],
    }
    task_id = client.post(
        f"/api/v1/classes/{r['code']}/followups", headers=r["headers"], json=body
    ).json()["id"]
    session_id = client.post(
        f"/api/v1/classes/{r['code']}/followups/{task_id}/start",
        headers=r["students"][0]["headers"],
    ).json()["session_id"]
    before = set(Path(settings.AUDIO_STORAGE_DIR).rglob("*"))
    original_probe = api.probe_audio

    def cancel_while_probing(data: bytes, suffix: str):
        task = db.get(ClassroomExercise, uuid.UUID(task_id))
        assert task is not None
        task.status = "followup_closed"
        db.add(task)
        db.commit()
        return original_probe(data, suffix)

    monkeypatch.setattr(api, "probe_audio", cancel_while_probing)
    response = client.post(
        "/api/v1/attempts",
        headers=r["students"][0]["headers"],
        data={
            "session_id": session_id,
            "item_id": str(r["ids"][0]),
            "item_type": "repeat",
            "duration_s": "5",
        },
        files={"audio": wav_upload()},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Followup cancelled"
    assert not db.exec(
        select(Attempt).where(Attempt.session_id == uuid.UUID(session_id))
    ).all()
    assert set(Path(settings.AUDIO_STORAGE_DIR).rglob("*")) == before


def test_focus_marker_is_loaded_with_the_board_batch(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    from sqlalchemy import event

    r = teaching_round
    r["attempt"].teacher_focus = True
    db.add(r["attempt"])
    db.commit()
    queries: list[str] = []
    engine = db.get_bind()

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/v1/classes/{r['code']}/board", headers=r["headers"]
        )
        assert response.status_code == 200
        alice = next(
            student
            for student in response.json()["students"]
            if student["student_id"] == str(r["original"].student_id)
        )
        assert any(item["teacher_focus"] for item in alice["items"])
        assert not any(
            "WHERE attempt.id =" in statement and "teacher_focus" in statement
            for statement in queries
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
