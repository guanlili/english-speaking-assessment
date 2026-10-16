"""今日当前发布的全班薄弱点。"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Attempt, Classroom, ClassroomExercise, PracticeSession
from tests.utils.credential import make_student


def test_weak_spots_group_shared_misses_for_the_teacher(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    ).json()
    code = classroom["code"]
    ada = make_student(db, client, code, "Ada")
    ben = make_student(db, client, code, "Ben")
    item_id = uuid.uuid4()
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        snapshot_items=[
            {
                "type": "repeat",
                "id": str(item_id),
                "text": "I usually visit the museum",
            }
        ],
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    today = datetime.now(ZoneInfo(settings.PRACTICE_TZ)).date()
    for made, transcript, overall in (
        (ada, "I visit the museum", 60),
        (ben, "I visit the museum", 64),
    ):
        practice = PracticeSession(
            classroom_id=row.id,
            student_id=uuid.UUID(made["student"]["id"]),
            band="B1",
            mode="daily",
            assignment_id=exercise.id,
            session_date=today,
        )
        db.add(practice)
        db.flush()
        db.add(
            Attempt(
                item_type="repeat",
                item_id=item_id,
                student_id=practice.student_id,
                session_id=practice.id,
                audio_path="test.wav",
                duration_s=4,
                status="done",
                transcript=transcript,
                overall=overall,
                item_snapshot={"text": "I usually visit the museum", "type": "repeat"},
            )
        )
    db.add(row)
    db.commit()

    denied = client.get(f"/api/v1/classes/{code}/weak-spots", headers=ada["headers"])
    assert denied.status_code == 403

    found = client.get(
        f"/api/v1/classes/{code}/weak-spots", headers=superuser_token_headers
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["word_gaps"] == [{"word": "usually", "student_count": 2}]
    assert body["low_items"][0]["item_id"] == str(item_id)
    assert body["low_items"][0]["low_count"] == 2
