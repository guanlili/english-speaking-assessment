"""Per-sentence timing survives publishing and never follows edited text."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Classroom, ClassroomExercise, Passage
from app.services.reading import expand_reading_items
from tests.api.routes.test_exam import _cleanup_classroom


def test_reading_durations_publish_and_edit(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    headers = superuser_token_headers
    passage = Passage(
        slug=f"timings-{uuid.uuid4()}",
        title="Timing",
        text="Read this. Read that!",
        reading_split=True,
    )
    db.add(passage)
    db.commit()
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=headers
    ).json()
    endpoint = f"/api/v1/admin/passages/{passage.id}"
    try:
        response = client.put(
            endpoint, json={"reading_sentence_seconds": [12, 34]}, headers=headers
        )
        assert response.status_code == 200, response.text
        db.refresh(passage)
        items = expand_reading_items(passage)
        assert [i["suggested_seconds"] for i in items] == [12, 34]
        response = client.put(
            f"/api/v1/classes/{classroom['code']}/assignment",
            json={
                "items": [{"type": "passage", "id": str(passage.id)}],
                "is_exam": True,
                "automated_exam": True,
                "time_limit_minutes": 5,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        row = db.get(Classroom, uuid.UUID(classroom["id"]))
        assert row is not None
        db.refresh(row)
        published = db.get(ClassroomExercise, row.current_exercise_id)
        assert published is not None
        assert [i["suggested_seconds"] for i in published.snapshot_items] == [12, 34]
        response = client.put(
            endpoint, json={"reading_sentence_seconds": [None, 50]}, headers=headers
        )
        assert response.status_code == 200
        db.refresh(passage)
        assert [i["suggested_seconds"] for i in expand_reading_items(passage)] == [
            4,
            50,
        ]
        db.refresh(published)
        assert [i["suggested_seconds"] for i in published.snapshot_items] == [12, 34]
        response = client.put(
            endpoint, json={"text": "Changed first. Read that!"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["reading_sentence_seconds"] is None
        response = client.put(
            endpoint,
            json={
                "reading_sentence_seconds": [99, 99],
                "reading_sentence_texts": ["Read this.", "Read that!"],
            },
            headers=headers,
        )
        assert response.status_code == 422
        db.refresh(passage)
        assert passage.reading_sentence_seconds is None
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(passage)
        db.commit()


@pytest.mark.parametrize("values", [[0, 10], [181, 10], [1.5, 10], [True, 10], [10]])
def test_reading_durations_validation(
    values: list[object],
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    passage = Passage(
        slug=f"timings-{uuid.uuid4()}",
        title="Timing",
        text="Read this. Read that!",
        reading_split=True,
    )
    db.add(passage)
    db.commit()
    try:
        response = client.put(
            f"/api/v1/admin/passages/{passage.id}",
            json={"reading_sentence_seconds": values},
            headers=superuser_token_headers,
        )
        assert response.status_code == 422
        db.refresh(passage)
        assert passage.reading_sentence_seconds is None
    finally:
        db.delete(passage)
        db.commit()
