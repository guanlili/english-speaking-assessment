# ruff: noqa: F811
"""P1 teaching loop: privacy, atomic assignments, and explicit acknowledgments."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Classroom, ClassroomExercise, FollowupBatch, get_datetime_utc
from tests.api.routes.test_feedback_followups import teaching_round  # noqa: F401


def test_review_drafts_publish_conflicts_and_withdraw(
    client: TestClient, teaching_round: dict
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    url = f"{base}/exercises/{r['source'].id}/review"
    teacher, student = r["headers"], r["students"][0]["headers"]
    assert client.get(url, headers=student).status_code == 403
    assert client.get(url, headers=teacher).json()["revision"] == 0
    body = {
        "expected_revision": 0,
        "attempt_id": str(r["attempt"].id),
        "note": "Private discussion advice",
        "summary": "Public class advice",
    }
    saved = client.put(url, headers=teacher, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["notes"][str(r["attempt"].id)] == "Private discussion advice"
    assert client.get(url, headers=teacher).json() == saved.json()
    assert client.put(url, headers=teacher, json=body).status_code == 409
    assert client.get(base + "/review-summaries", headers=student).json() == []
    published = client.post(
        url + "/publish", headers=teacher, json={"expected_revision": 1}
    )
    assert published.status_code == 200, published.text
    public = client.get(base + "/review-summaries", headers=student).json()
    assert len(public) == 1 and public[0]["text"] == "Public class advice"
    assert "Private" not in str(public) and "notes" not in public[0]
    assert (
        client.put(
            url, headers=teacher, json={"expected_revision": 2, "summary": "New draft"}
        ).status_code
        == 200
    )
    assert (
        client.get(base + "/review-summaries", headers=student).json()[0]["text"]
        == "Public class advice"
    )
    assert (
        client.post(
            url + "/withdraw", headers=teacher, json={"expected_revision": 3}
        ).status_code
        == 200
    )
    assert client.get(base + "/review-summaries", headers=student).json() == []
    assert (
        client.put(
            url,
            headers=teacher,
            json={
                "expected_revision": 4,
                "attempt_id": str(uuid.uuid4()),
                "note": "invalid",
            },
        ).status_code
        == 404
    )


def test_exam_review_cannot_publish_or_expose_notes(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    r["source"].is_exam = True
    r["source"].time_limit_minutes = 30
    r["original"].exam_started_at = get_datetime_utc()
    db.add(r["source"])
    db.add(r["original"])
    db.commit()
    url = f"/api/v1/classes/{r['code']}/exercises/{r['source'].id}/review"
    assert (
        client.put(
            url, headers=r["headers"], json={"expected_revision": 0, "summary": "Draft"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            url + "/publish", headers=r["headers"], json={"expected_revision": 1}
        ).status_code
        == 422
    )
    assert (
        client.put(
            url,
            headers=r["headers"],
            json={
                "expected_revision": 1,
                "attempt_id": str(r["attempt"].id),
                "note": "Hidden",
            },
        ).status_code
        == 422
    )


def test_individual_assignments_group_and_deduplicate(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    ids = [str(s["student"]["id"]) for s in r["students"]]
    body = {
        "request_id": str(uuid.uuid4()),
        "source_exercise_id": str(r["source"].id),
        "title": "Individual practice",
        "targets": [
            {"student_id": ids[0], "item_ids": [str(r["ids"][0])]},
            {"student_id": ids[1], "item_ids": [str(r["ids"][1])]},
            {"student_id": ids[2], "item_ids": [str(r["ids"][0])]},
        ],
    }
    url = base + "/followups/individualized"
    assert (
        client.post(url, headers=r["students"][0]["headers"], json=body).status_code
        == 403
    )
    response = client.post(url, headers=r["headers"], json=body)
    assert response.status_code == 200, response.text
    tasks = response.json()["task_ids"]
    assert len(tasks) == 2
    assert client.post(url, headers=r["headers"], json=body).json()["task_ids"] == tasks
    for task_id in tasks:
        task = db.get(ClassroomExercise, uuid.UUID(task_id))
        assert task and len(task.snapshot_items) == 1
        expected = (
            [ids[0], ids[2]]
            if task.snapshot_items[0]["id"] == str(r["ids"][0])
            else [ids[1]]
        )
        assert {t["student_id"] for t in task.target_students or []} == set(expected)
    classroom = db.get(Classroom, r["classroom"].id)
    assert classroom and classroom.current_exercise_id == r["source"].id
    body["title"] = "Changed payload"
    assert client.post(url, headers=r["headers"], json=body).status_code == 409
    visible = client.get(
        base + "/followups", headers=r["students"][0]["headers"]
    ).json()
    assert len(visible) == 1 and [t["student_id"] for t in visible[0]["targets"]] == [
        ids[0]
    ]


def test_individual_batch_rolls_back_all_groups(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    request_id = uuid.uuid4()
    body = {
        "request_id": str(request_id),
        "source_exercise_id": str(r["source"].id),
        "title": "Must not partially publish",
        "targets": [
            {
                "student_id": str(r["students"][0]["student"]["id"]),
                "item_ids": [str(r["ids"][0])],
            },
            {
                "student_id": str(r["students"][1]["student"]["id"]),
                "item_ids": [str(uuid.uuid4())],
            },
        ],
    }
    response = client.post(
        f"/api/v1/classes/{r['code']}/followups/individualized",
        headers=r["headers"],
        json=body,
    )
    assert response.status_code == 422, response.text
    assert db.get(FollowupBatch, request_id) is None
    assert (
        db.exec(
            select(ClassroomExercise).where(
                ClassroomExercise.classroom_id == r["classroom"].id,
                ClassroomExercise.status == "followup",
            )
        ).all()
        == []
    )


def test_help_and_reminders_permissions_lifecycle_and_retry(
    client: TestClient, teaching_round: dict, normal_user_token_headers: dict[str, str]
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    teacher, student, other = (
        r["headers"],
        r["students"][0]["headers"],
        r["students"][1]["headers"],
    )
    body = {
        "request_id": str(uuid.uuid4()),
        "category": "audio",
        "text": "Cannot hear playback",
    }
    response = client.post(base + "/help-requests", headers=student, json=body)
    assert response.status_code == 200, response.text
    message = response.json()
    action = base + "/class-messages/" + message["id"]
    assert (
        client.post(base + "/help-requests", headers=student, json=body).json()["id"]
        == message["id"]
    )
    assert (
        client.post(
            base + "/help-requests",
            headers=student,
            json={**body, "request_id": str(uuid.uuid4())},
        ).status_code
        == 409
    )
    assert client.post(action + "/resolved", headers=student).status_code == 403
    assert client.post(action + "/withdrawn", headers=other).status_code == 404
    assert (
        client.get(
            base + "/class-messages?kind=help", headers=normal_user_token_headers
        ).status_code
        == 403
    )
    assert client.post(action + "/read", headers=teacher).json()["read_at"]
    assert client.get(base + "/my-messages", headers=student).json()[0]["read_at"]
    assert (
        client.post(action + "/resolved", headers=teacher).json()["resolution"]
        == "resolved"
    )
    assert (
        client.get(
            base + "/class-messages?kind=help&status=open", headers=teacher
        ).json()
        == []
    )
    second = client.post(
        base + "/help-requests",
        headers=student,
        json={**body, "request_id": str(uuid.uuid4())},
    ).json()
    assert (
        client.post(
            base + "/class-messages/" + second["id"] + "/withdrawn", headers=student
        ).json()["resolution"]
        == "withdrawn"
    )
    reminder = {
        "request_id": str(uuid.uuid4()),
        "student_ids": [str(r["students"][0]["student"]["id"])],
        "text": "Please finish the practice",
    }
    assert (
        client.post(base + "/reminders", headers=student, json=reminder).status_code
        == 403
    )
    sent = client.post(base + "/reminders", headers=teacher, json=reminder)
    assert sent.status_code == 200, sent.text
    rows = sent.json()
    assert len(rows) == 1
    assert (
        client.post(base + "/reminders", headers=teacher, json=reminder).json()[0]["id"]
        == rows[0]["id"]
    )
    assert (
        client.post(
            base + "/reminders", headers=teacher, json={**reminder, "text": "Changed"}
        ).status_code
        == 409
    )
    assert client.get(base + "/my-messages", headers=other).json() == []
    receipt = base + "/class-messages/" + rows[0]["id"] + "/read"
    assert client.post(receipt, headers=teacher).status_code == 403
    assert client.post(receipt, headers=other).status_code == 404
    assert (
        client.get(base + "/class-messages?kind=reminder", headers=teacher).json()[0][
            "read_at"
        ]
        is None
    )
    assert client.post(receipt, headers=student).json()["read_at"]
    assert (
        client.get(
            base + "/class-messages?kind=reminder&status=open", headers=teacher
        ).json()
        == []
    )
