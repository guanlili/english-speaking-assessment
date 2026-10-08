"""课堂删除：归档成员、历史记录、停用课堂和级联顺序。"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    PracticeSession,
    Student,
    User,
    VocabularyAnswer,
    VocabularySession,
)
from tests.utils.credential import make_student


def _class(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_delete_inactive_classroom(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    classroom = _class(client, superuser_token_headers)
    row = db.get(Classroom, uuid.UUID(classroom["id"]))
    assert row is not None
    row.is_active = False
    db.add(row)
    db.commit()
    response = client.delete(
        f"/api/v1/classes/{classroom['code'].lower()}", headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Classroom, uuid.UUID(classroom["id"])) is None


@pytest.mark.parametrize("kind", ["oral", "vocabulary"])
def test_confirm_delete_archived_history_preserves_account_and_other_class(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    kind: str,
) -> None:
    classroom = _class(client, superuser_token_headers)
    other = _class(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"])
    student_id = uuid.UUID(made["student"]["id"])
    classroom_id = uuid.UUID(classroom["id"])
    if kind == "oral":
        ps = PracticeSession(
            classroom_id=classroom_id,
            student_id=student_id,
            band="B1",
            session_date=date.today(),
        )
        db.add(ps)
        db.flush()
        answer = Attempt(
            student_id=student_id,
            session_id=ps.id,
            item_id=uuid.uuid4(),
            audio_path="unused-test-audio",
            duration_s=6,
            status="done",
        )
    else:
        ps = VocabularySession(classroom_id=classroom_id, student_id=student_id)
        db.add(ps)
        db.flush()
        answer = VocabularyAnswer(
            session_id=ps.id,
            item_index=0,
            answer_raw="cat",
            answer_normalized="cat",
            is_correct=True,
            word_id=uuid.uuid4(),
            headword="cat",
            meaning_zh="猫",
        )
    db.add(answer)
    db.commit()
    session_id, answer_id = ps.id, answer.id
    removed = client.delete(
        f"/api/v1/students/{student_id}", headers=superuser_token_headers
    )
    assert removed.status_code == 200, removed.text
    db.expire_all()
    student = db.get(Student, student_id)
    assert student is not None and student.user_id is None
    url = f"/api/v1/classes/{classroom['code']}"
    assert client.delete(url, headers=superuser_token_headers).status_code == 409
    response = client.delete(
        url, params={"delete_history": True}, headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Classroom, classroom_id) is None
    assert db.get(Student, student_id) is None
    assert db.get(type(ps), session_id) is None
    assert db.get(type(answer), answer_id) is None
    assert db.get(User, made["user"].id) is not None
    assert db.get(Classroom, uuid.UUID(other["id"])) is not None


@pytest.mark.parametrize("status", ["queued", "scoring"])
def test_delete_waits_for_scoring(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    status: str,
) -> None:
    classroom = _class(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"])
    answer = Attempt(
        student_id=uuid.UUID(made["student"]["id"]),
        item_id=uuid.uuid4(),
        audio_path="unused-test-audio",
        duration_s=6,
        status=status,
    )
    db.add(answer)
    db.commit()
    response = client.delete(
        f"/api/v1/classes/{classroom['code']}",
        params={"delete_history": True},
        headers=superuser_token_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "有正在评分中的作答，请稍后再删除"
    db.refresh(answer)
    assert answer.status == status
    # 防止测试 worker 恢复器碰到假音频路径。
    answer.status = "failed"
    db.add(answer)
    db.commit()


def test_delete_multiple_publications_without_unique_constraint_collision(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    classroom = _class(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"])
    classroom_id = uuid.UUID(classroom["id"])
    student_id = uuid.UUID(made["student"]["id"])
    for version in (1, 2):
        exercise = ClassroomExercise(
            classroom_id=classroom_id,
            version_no=version,
            snapshot_items=[],
        )
        db.add(exercise)
        db.flush()
        db.add(
            PracticeSession(
                classroom_id=classroom_id,
                student_id=student_id,
                assignment_id=exercise.id,
                band="B1",
                session_date=date.today(),
            )
        )
    db.commit()
    response = client.delete(
        f"/api/v1/classes/{classroom['code']}", headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    assert (
        db.exec(
            select(PracticeSession).where(PracticeSession.student_id == student_id)
        ).all()
        == []
    )


def test_delete_requires_classroom_permission(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    classroom = _class(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"])
    response = client.delete(
        f"/api/v1/classes/{classroom['code']}",
        params={"delete_history": True},
        headers=made["headers"],
    )
    assert response.status_code == 403
