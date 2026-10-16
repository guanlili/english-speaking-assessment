"""课后作业与课上当前发布并存。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Classroom, Passage
from tests.utils.credential import make_student


def test_homework_publish_does_not_replace_the_class_exercise(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    ).json()
    code = classroom["code"]
    student = make_student(db, client, code, "Ada")
    class_passage = Passage(
        slug=f"class-{uuid.uuid4().hex[:8]}",
        title="Class article",
        text="Read this in class today.",
        cefr_band="B1",
    )
    home_passage = Passage(
        slug=f"home-{uuid.uuid4().hex[:8]}",
        title="Home article",
        text="Read this after class.",
        cefr_band="B1",
    )
    db.add(class_passage)
    db.add(home_passage)
    db.commit()
    headers = superuser_token_headers
    published = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "title": "课上练习",
            "is_exam": True,
            "time_limit_minutes": 20,
            "items": [{"type": "passage", "id": str(class_passage.id)}],
        },
        headers=headers,
    )
    assert published.status_code == 200, published.text
    row = db.get(Classroom, classroom["id"])
    assert row is not None
    db.refresh(row)
    class_exercise = row.current_exercise_id

    rejected = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "slot": "homework",
            "is_exam": True,
            "time_limit_minutes": 20,
            "items": [{"type": "passage", "id": str(home_passage.id)}],
        },
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "课后作业不能开启模考"

    homework = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "slot": "homework",
            "title": "课后作业",
            "items": [{"type": "passage", "id": str(home_passage.id)}],
        },
        headers=headers,
    )
    assert homework.status_code == 200, homework.text
    db.refresh(row)
    assert row.current_exercise_id == class_exercise
    assert row.homework_exercise_id is not None
    assert row.homework_exercise_id != class_exercise

    class_plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    )
    assert class_plan.status_code == 200, class_plan.text
    assert class_plan.json()["homework_title"] == "课后作业"
    assert any("in class" in item["text"] for item in class_plan.json()["items"])

    home_plan = client.get(
        f"/api/v1/classes/{code}/today?slot=homework", headers=student["headers"]
    )
    assert home_plan.status_code == 200, home_plan.text
    assert any("after class" in item["text"] for item in home_plan.json()["items"])
    assert home_plan.json()["session_id"] != class_plan.json()["session_id"]

    cleared = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"slot": "homework", "items": []},
        headers=headers,
    )
    assert cleared.status_code == 200
    db.refresh(row)
    assert row.current_exercise_id == class_exercise
    assert row.homework_exercise_id is None
