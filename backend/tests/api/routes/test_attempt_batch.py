"""Batch feedback reads: atomic classroom authorization and public projection.

These tests use the isolated app_test fixture from tests/conftest.py.
"""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session

from app.api.routes.attempts import AttemptBatchRead, read_attempts_batch
from app.core.security import create_access_token
from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    PracticeSession,
    Student,
    User,
    get_datetime_utc,
)

BATCH_URL = "/api/v1/attempts/batch-read"
ACCESS_DENIED = "没有权限：您不是该作答所属课堂的授权教师"


@dataclass
class BatchData:
    teacher: User
    student_user: User
    classrooms: list[Classroom]
    students: list[Student]
    attempts: list[Attempt]


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def batch_data(db: Session) -> Generator[BatchData]:
    users = [
        User(
            email=f"batch-{uuid.uuid4().hex}@example.com",
            role=role,
            hashed_password="unused-batch-test-password",
        )
        for role in ("teacher", "teacher", "student")
    ]
    db.add_all(users)
    db.flush()
    classrooms = [
        Classroom(code=uuid.uuid4().hex[:12], owner_id=owner.id)
        for owner in (users[0], users[0], users[1])
    ]
    db.add_all(classrooms)
    db.flush()
    # One account in three classrooms: permission must follow the specific
    # student profile's classroom, not another class shared with that account.
    students = [
        Student(classroom_id=room.id, user_id=users[2].id, display_name="Alice")
        for room in classrooms
    ]
    db.add_all(students)
    db.flush()
    attempts = [
        Attempt(
            student_id=student.id if student is not None else None,
            item_id=uuid.uuid4(),
            item_type="question",
            item_snapshot={"title": "Saved title", "text": f"Frozen prompt {index}"},
            audio_path="private-batch-test-audio",
            duration_s=5,
            status="done",
            transcript="Saved transcript",
            overall=80 + index,
            advice=["Saved advice"],
            rubric={"status": "pending"},
            teacher_feedback="Saved teacher feedback",
            teacher_focus=True,
            teacher_feedback_author="Teacher",
            teacher_feedback_at=get_datetime_utc(),
            teacher_feedback_revision=2,
        )
        for index, student in enumerate([*students, None])
    ]
    db.add_all(attempts)
    db.commit()
    yield BatchData(users[0], users[2], classrooms, students, attempts)
    db.rollback()
    # Explicitly flush dependency layers; no unrelated fixtures are deleted.
    for rows in (attempts, students, classrooms, users):
        for row in rows:
            db.delete(row)
        db.flush()
    db.commit()


def test_batch_deduplicates_in_order_and_matches_single_read(
    client: TestClient, batch_data: BatchData
) -> None:
    headers = _headers(batch_data.teacher)
    ids = [str(batch_data.attempts[index].id) for index in (1, 0, 3, 1)]
    response = client.post(BATCH_URL, headers=headers, json={"attempt_ids": ids})
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == ids[:3]
    for row in response.json():
        single = client.get(f"/api/v1/attempts/{row['id']}", headers=headers)
        assert single.status_code == 200
        assert row == single.json()
        assert row["item_text"].startswith("Frozen prompt")
        assert row["teacher_feedback_revision"] == 2
        assert "audio_path" not in row and "item_snapshot" not in row


@pytest.mark.parametrize("foreign_first", [False, True])
def test_batch_rejects_entire_mixed_classroom_request(
    client: TestClient, batch_data: BatchData, foreign_first: bool
) -> None:
    ids = [str(batch_data.attempts[index].id) for index in (0, 2)]
    if foreign_first:
        ids.reverse()
    response = client.post(
        BATCH_URL, headers=_headers(batch_data.teacher), json={"attempt_ids": ids}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": ACCESS_DENIED}


def test_batch_rejects_ownerless_classroom(
    client: TestClient, db: Session, batch_data: BatchData
) -> None:
    batch_data.classrooms[0].owner_id = None
    db.add(batch_data.classrooms[0])
    db.commit()
    response = client.post(
        BATCH_URL,
        headers=_headers(batch_data.teacher),
        json={"attempt_ids": [str(batch_data.attempts[0].id)]},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": ACCESS_DENIED}


def test_batch_administrator_can_read_across_classrooms(
    client: TestClient,
    batch_data: BatchData,
    superuser_token_headers: dict[str, str],
) -> None:
    ids = [str(attempt.id) for attempt in batch_data.attempts]
    response = client.post(
        BATCH_URL, headers=superuser_token_headers, json={"attempt_ids": ids}
    )
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == ids


def test_batch_requires_teacher_even_for_own_or_anonymous_attempt(
    client: TestClient, batch_data: BatchData
) -> None:
    for index in (0, 3):
        body = {"attempt_ids": [str(batch_data.attempts[index].id)]}
        assert client.post(BATCH_URL, json=body).status_code == 401
        response = client.post(
            BATCH_URL, headers=_headers(batch_data.student_user), json=body
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "该操作需要角色：teacher"}
    # The existing own-student single-read route is unchanged.
    assert (
        client.get(
            f"/api/v1/attempts/{batch_data.attempts[0].id}",
            headers=_headers(batch_data.student_user),
        ).status_code
        == 200
    )


@pytest.mark.parametrize("missing_first", [False, True])
def test_batch_missing_attempt_returns_no_partial_feedback(
    client: TestClient, batch_data: BatchData, missing_first: bool
) -> None:
    ids = [str(batch_data.attempts[0].id), str(uuid.uuid4())]
    if missing_first:
        ids.reverse()
    response = client.post(
        BATCH_URL, headers=_headers(batch_data.teacher), json={"attempt_ids": ids}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Attempt not found"}


def test_batch_limit_is_checked_before_deduplication(
    client: TestClient, batch_data: BatchData
) -> None:
    headers = _headers(batch_data.teacher)
    attempt_id = str(batch_data.attempts[0].id)
    allowed = client.post(
        BATCH_URL, headers=headers, json={"attempt_ids": [attempt_id] * 100}
    )
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1
    for ids in ([attempt_id] * 101, [str(uuid.uuid4()) for _ in range(101)]):
        response = client.post(BATCH_URL, headers=headers, json={"attempt_ids": ids})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "attempt_ids"]


def test_batch_accepts_100_distinct_attempts(
    client: TestClient, db: Session, batch_data: BatchData
) -> None:
    extra = [
        Attempt(
            student_id=batch_data.students[0].id,
            item_id=uuid.uuid4(),
            audio_path="unused-batch-limit-test",
            duration_s=5,
            status="done",
        )
        for _ in range(100)
    ]
    db.add_all(extra)
    db.commit()
    try:
        ids = [str(attempt.id) for attempt in extra]
        response = client.post(
            BATCH_URL,
            headers=_headers(batch_data.teacher),
            json={"attempt_ids": ids},
        )
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()] == ids
    finally:
        for attempt in extra:
            db.delete(attempt)
        db.commit()


@pytest.mark.parametrize("body", [{}, {"attempt_ids": []}, {"attempt_ids": ["bad-id"]}])
def test_batch_validates_request(
    client: TestClient, batch_data: BatchData, body: dict[str, object]
) -> None:
    response = client.post(BATCH_URL, headers=_headers(batch_data.teacher), json=body)
    assert response.status_code == 422


def test_batch_preserves_teacher_exam_feedback_and_student_mask(
    client: TestClient,
    db: Session,
    batch_data: BatchData,
    superuser_token_headers: dict[str, str],
) -> None:
    attempt = batch_data.attempts[0]
    exercise = ClassroomExercise(
        classroom_id=batch_data.classrooms[0].id,
        is_exam=True,
        time_limit_minutes=30,
        snapshot_items=[
            {
                "id": str(attempt.item_id),
                "type": "question",
                "text": "First question?",
                "suggested_seconds": 60,
            },
            {
                "id": str(uuid.uuid4()),
                "type": "question",
                "text": "Next question?",
                "suggested_seconds": 60,
            },
        ],
    )
    db.add(exercise)
    db.flush()
    practice = PracticeSession(
        classroom_id=exercise.classroom_id,
        student_id=batch_data.students[0].id,
        assignment_id=exercise.id,
        band="B1",
        session_date=get_datetime_utc().date(),
        exam_started_at=get_datetime_utc(),
    )
    db.add(practice)
    db.flush()
    attempt.session_id = practice.id
    db.add(attempt)
    db.commit()
    try:
        body = {"attempt_ids": [str(attempt.id)]}
        for headers in (_headers(batch_data.teacher), superuser_token_headers):
            response = client.post(BATCH_URL, headers=headers, json=body)
            assert response.status_code == 200
            row = response.json()[0]
            assert row["overall"] == 80
            assert row["transcript"] == "Saved transcript"
            assert row["rubric"] == {"status": "pending"}
            assert row["teacher_feedback"] == "Saved teacher feedback"
            assert row["teacher_focus"] and row["teacher_feedback_revision"] == 2
            assert (
                row
                == client.get(f"/api/v1/attempts/{attempt.id}", headers=headers).json()
            )
        masked = client.get(
            f"/api/v1/attempts/{attempt.id}", headers=_headers(batch_data.student_user)
        )
        assert masked.status_code == 200
        for key in ("overall", "transcript", "rubric", "teacher_feedback"):
            assert masked.json()[key] is None
        assert masked.json()["teacher_focus"] is False
        assert masked.json()["teacher_feedback_revision"] == 0
    finally:
        attempt.session_id = None
        db.add(attempt)
        db.flush()
        db.delete(practice)
        db.flush()
        db.delete(exercise)
        db.commit()


def test_batch_queries_do_not_grow_per_attempt(
    db: Session, batch_data: BatchData
) -> None:
    body = AttemptBatchRead(
        attempt_ids=[attempt.id for attempt in batch_data.attempts[:2]]
    )
    teacher_id = batch_data.teacher.id
    statements: list[str] = []

    def capture(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    # Capture this connection only, excluding background worker queries.
    with Session(db.get_bind()) as session:
        teacher = session.get(User, teacher_id)
        assert teacher is not None
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", capture)
        try:
            result = read_attempts_batch(session, body, teacher)
            assert len(result) == 2
            assert (
                len(statements) == 2
            )  # Attempt IN + Student/Classroom ownership join.
            assert "JOIN classroom" in statements[1]
        finally:
            event.remove(connection, "before_cursor_execute", capture)
