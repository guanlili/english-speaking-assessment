# ruff: noqa: F811
"""Evidence matching and help/reminder workflow boundaries."""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Attempt, ClassroomMessage, PracticeSession, get_datetime_utc
from tests.api.routes.test_feedback_followups import teaching_round  # noqa: F401


def test_outcomes_use_latest_before_assignment_and_latest_followup(
    client: TestClient,
    db: Session,
    teaching_round: dict,
    normal_user_token_headers: dict[str, str],
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    task = client.post(
        base + "/followups",
        headers=r["headers"],
        json={
            "source_exercise_id": str(r["source"].id),
            "student_ids": [str(r["original"].student_id)],
            "item_ids": [str(r["ids"][0]), str(r["ids"][1])],
            "title": "Outcome check",
        },
    ).json()
    url = base + "/followups/" + task["id"] + "/outcomes"
    assert client.get(url, headers=r["students"][0]["headers"]).status_code == 403
    assert client.get(url, headers=normal_user_token_headers).status_code == 403
    result = client.get(url, headers=r["headers"])
    assert result.status_code == 200, result.text
    item = result.json()["students"][0]["items"][0]
    assert item["original"]["attempt_id"] == str(r["attempt"].id)
    assert item["followup"] is None and item["reference_change"] is None
    later = Attempt(
        session_id=r["original"].id,
        student_id=r["original"].student_id,
        item_id=r["ids"][0],
        item_type="repeat",
        audio_path="unused",
        duration_s=2,
        status="done",
        overall=1,
    )
    db.add(later)
    db.commit()
    started = client.post(
        base + "/followups/" + task["id"] + "/start",
        headers=r["students"][0]["headers"],
    ).json()
    ps = db.get(PracticeSession, uuid.UUID(started["session_id"]))
    assert ps
    first = Attempt(
        session_id=ps.id,
        student_id=ps.student_id,
        item_id=r["ids"][0],
        item_type="repeat",
        audio_path="unused",
        duration_s=2,
        status="done",
        overall=95,
        teacher_feedback="Good detail",
        teacher_focus=True,
    )
    db.add(first)
    db.commit()
    result = client.get(url, headers=r["headers"]).json()
    row = result["students"][0]
    assert row["completed_items"] == 1 and row["total_items"] == 2
    assert row["items"][0]["reference_change"] == 7
    assert row["items"][0]["original"]["overall"] == 88
    assert row["items"][0]["followup"]["teacher_feedback"] == "Good detail"
    assert row["items"][1]["original"] is None
    newer = Attempt(
        session_id=ps.id,
        student_id=ps.student_id,
        item_id=r["ids"][0],
        item_type="repeat",
        audio_path="unused",
        duration_s=2,
        status="queued",
        overall=None,
    )
    db.add(newer)
    db.commit()
    item = client.get(url, headers=r["headers"]).json()["students"][0]["items"][0]
    assert item["followup"]["status"] == "queued" and item["reference_change"] is None
    newer.status = "done"
    newer.overall = 96
    newer.engine = "ark"
    db.add(newer)
    db.commit()
    assert (
        client.get(url, headers=r["headers"]).json()["students"][0]["items"][0][
            "reference_change"
        ]
        is None
    )
    page = client.get(url + "?offset=1&limit=1", headers=r["headers"]).json()
    assert page["students"] == [] and page["total_students"] == 1
    r["source"].is_exam = True
    db.add(r["source"])
    db.commit()
    assert client.get(url, headers=r["headers"]).status_code == 422


def test_help_reply_visible_to_own_student_and_conflict_safe(
    client: TestClient, teaching_round: dict
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    student = r["students"][0]["headers"]
    row = client.post(
        base + "/help-requests",
        headers=student,
        json={"request_id": str(uuid.uuid4()), "category": "audio"},
    ).json()
    url = base + "/class-messages/" + row["id"] + "/reply"
    body = {
        "text": "Try enabling sound again",
        "expected_revision": 0,
        "resolve": False,
    }
    assert client.put(url, headers=student, json=body).status_code == 403
    saved = client.put(url, headers=r["headers"], json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["resolved_at"] is None and saved.json()["read_at"]
    assert client.put(url, headers=r["headers"], json=body).status_code == 409
    assert (
        client.get(base + "/my-messages", headers=student).json()[0]["reply_text"]
        == body["text"]
    )
    assert (
        client.get(base + "/my-messages", headers=r["students"][1]["headers"]).json()
        == []
    )
    resolved = client.put(
        url,
        headers=r["headers"],
        json={**body, "expected_revision": 1, "resolve": True},
    )
    assert resolved.json()["resolution"] == "resolved"
    assert (
        client.get(
            base + "/class-messages?kind=help&status=open", headers=r["headers"]
        ).json()
        == []
    )
    assert (
        client.get(
            base + "/class-messages?kind=help&status=all", headers=r["headers"]
        ).json()[0]["reply_text"]
        == body["text"]
    )


def test_reminder_deadline_repeat_dedup_and_explicit_chain_ack(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    base = f"/api/v1/classes/{r['code']}"
    body = {
        "request_id": str(uuid.uuid4()),
        "student_ids": [str(r["original"].student_id)],
        "text": "Finish your answer",
        "due_at": (get_datetime_utc() + timedelta(hours=1)).isoformat(),
    }
    naive = {**body, "due_at": "2026-10-20T12:00:00"}
    assert (
        client.post(base + "/reminders", headers=r["headers"], json=naive).status_code
        == 422
    )
    assert (
        client.post(
            base + "/reminders",
            headers=r["headers"],
            json={
                **body,
                "due_at": (get_datetime_utc() - timedelta(hours=1)).isoformat(),
            },
        ).status_code
        == 422
    )
    sent = client.post(base + "/reminders", headers=r["headers"], json=body)
    assert sent.status_code == 200, sent.text
    row = sent.json()[0]
    assert row["due_at"] and row["read_at"] is None
    assert (
        client.post(base + "/reminders", headers=r["headers"], json=body).json()[0][
            "id"
        ]
        == row["id"]
    )
    request = {"request_id": str(uuid.uuid4())}
    repeat_url = base + "/reminders/" + row["id"] + "/repeat"
    assert (
        client.post(
            repeat_url, headers=r["students"][0]["headers"], json=request
        ).status_code
        == 403
    )
    assert (
        client.post(repeat_url, headers=r["headers"], json=request).status_code == 429
    )
    original = db.get(ClassroomMessage, uuid.UUID(row["id"]))
    assert original
    original.created_at = get_datetime_utc() - timedelta(minutes=2)
    db.add(original)
    db.commit()
    repeated = client.post(repeat_url, headers=r["headers"], json=request)
    assert repeated.status_code == 200, repeated.text
    assert (
        repeated.json()["reminder_of"] == row["id"]
        and repeated.json()["due_at"] == row["due_at"]
    )
    assert (
        client.post(repeat_url, headers=r["headers"], json=request).json()["id"]
        == repeated.json()["id"]
    )
    assert (
        len(
            db.exec(
                select(ClassroomMessage).where(
                    ClassroomMessage.classroom_id == r["classroom"].id
                )
            ).all()
        )
        == 2
    )
    assert (
        client.get(
            base + "/class-messages?kind=reminder&status=open", headers=r["headers"]
        ).json()[0]["read_at"]
        is None
    )
    read_url = base + "/class-messages/" + repeated.json()["id"] + "/read"
    assert client.post(read_url, headers=r["students"][1]["headers"]).status_code == 404
    assert client.post(read_url, headers=r["students"][0]["headers"]).status_code == 200
    assert (
        client.get(
            base + "/class-messages?kind=reminder&status=open", headers=r["headers"]
        ).json()
        == []
    )
    assert (
        client.post(
            repeat_url, headers=r["headers"], json={"request_id": str(uuid.uuid4())}
        ).status_code
        == 409
    )
