# ruff: noqa: F811  # Imported pytest fixtures are injected by parameter name.
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import Attempt, Passage, RepeatSentence, Student, get_datetime_utc
from tests.api.routes.test_content_ownership import teachers  # noqa: F401
from tests.api.routes.test_feedback_followups import teaching_round  # noqa: F401


def test_presence_permissions_scope_and_expiry(
    client: TestClient,
    db: Session,
    teaching_round: dict,
    normal_user_token_headers: dict[str, str],
) -> None:
    r = teaching_round
    url = f"/api/v1/classes/{r['code']}"
    headers = r["students"][0]["headers"]
    body = {
        "activity": "recording",
        "session_id": str(r["original"].id),
        "device_check": "passed",
    }
    assert (
        client.put(
            url + "/activity", json=body, headers=r["students"][1]["headers"]
        ).status_code
        == 404
    )
    assert client.put(url + "/activity", json=body, headers=headers).status_code == 200
    assert client.get(url + "/presence", headers=headers).status_code == 403
    assert (
        client.get(url + "/presence", headers=normal_user_token_headers).status_code
        == 403
    )
    assert (
        client.put(
            url + "/activity", json={"activity": "uploading"}, headers=headers
        ).status_code
        == 200
    )
    row = next(
        row
        for row in client.get(url + "/presence", headers=r["headers"]).json()
        if row["student_id"] == str(r["original"].student_id)
    )
    assert row["activity"] == "uploading" and row["device_check"] == "passed"
    student = db.get(Student, r["original"].student_id)
    assert student
    state = dict(student.classroom_activity or {})
    state["observed_at"] = (get_datetime_utc() - timedelta(seconds=100)).isoformat()
    student.classroom_activity = state
    db.add(student)
    db.commit()
    row = next(
        row
        for row in client.get(url + "/presence", headers=r["headers"]).json()
        if row["student_id"] == str(student.id)
    )
    assert row["activity"] == "unknown" and row["device_check"] == "passed"


def test_diagnostic_selection_uses_latest_answers_and_blocks_exam(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    a = r["attempt"]
    a.overall = 45
    a.transcript = "Original sentence"
    db.add(a)
    db.commit()
    url = f"/api/v1/classes/{r['code']}/diagnostic-targets"

    def read(rule: str, **extra):
        return client.get(url, params={"rule": rule, **extra}, headers=r["headers"])

    assert read("low_score").json()["student_ids"] == [str(a.student_id)]
    assert read("missed_word", word="frozen").json()["item_ids"] == [str(a.item_id)]
    newer = Attempt(
        session_id=a.session_id,
        student_id=a.student_id,
        item_type=a.item_type,
        item_id=a.item_id,
        item_snapshot=a.item_snapshot,
        audio_path="unused",
        duration_s=3,
        status="done",
        overall=95,
        transcript="Original frozen sentence",
    )
    db.add(newer)
    db.commit()
    assert read("low_score").json()["student_ids"] == []
    assert read("missed_word", word="frozen").json()["item_ids"] == []
    assert (
        client.get(
            url, params={"rule": "low_score"}, headers=r["students"][0]["headers"]
        ).status_code
        == 403
    )
    r["source"].is_exam = True
    db.add(r["source"])
    db.commit()
    assert read("low_score").status_code == 409


def test_reviews_comparison_report_and_exam_mask(
    client: TestClient, db: Session, teaching_round: dict
) -> None:
    r = teaching_round
    a = r["attempt"]
    headers = r["students"][0]["headers"]
    feedback = client.put(
        f"/api/v1/attempts/{a.id}/teacher-feedback",
        headers=r["headers"],
        json={
            "text": "Try again with one detail.",
            "focus": True,
            "review_tags": ["transcript_error"],
            "expected_revision": 0,
        },
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["teacher_review_tags"] == ["transcript_error"]
    assert feedback.json()["overall"] == 88
    legacy = client.put(
        f"/api/v1/attempts/{a.id}/teacher-feedback",
        headers=r["headers"],
        json={"text": "Updated advice", "focus": True, "expected_revision": 1},
    )
    assert legacy.status_code == 200
    assert legacy.json()["teacher_review_tags"] == ["transcript_error"]
    comparison = f"/api/v1/attempts/{a.id}/comparison"
    assert client.get(comparison, headers=headers).json() == []
    second = Attempt(
        session_id=a.session_id,
        student_id=a.student_id,
        item_type=a.item_type,
        item_id=a.item_id,
        item_snapshot=a.item_snapshot,
        audio_path="unused",
        duration_s=4,
        status="done",
        overall=95,
        transcript="My second answer",
    )
    db.add(second)
    db.commit()
    compared = client.get(comparison, headers=headers).json()
    assert [row["id"] for row in compared] == [str(a.id), str(second.id)]
    assert (
        client.get(comparison, headers=r["students"][1]["headers"]).status_code == 403
    )
    report_url = f"/api/v1/classes/{r['code']}/learning-report"
    report = client.get(report_url, headers=headers).json()
    assert report["completed_items"] == 1 and report["total_items"] == 2
    assert report["reading_avg"] == 95 and report["question_avg"] is None
    assert report["speaking_minutes"] == 0.1
    assert (
        client.get(
            report_url,
            params={"student_id": str(r["students"][1]["student"]["id"])},
            headers=headers,
        ).status_code
        == 403
    )
    r["source"].is_exam = True
    r["source"].time_limit_minutes = 30
    r["original"].exam_started_at = get_datetime_utc()
    db.add(r["source"])
    db.add(r["original"])
    db.commit()
    masked = client.get(f"/api/v1/attempts/{a.id}", headers=headers).json()
    assert masked["teacher_review_tags"] is None
    plan = client.get(f"/api/v1/classes/{r['code']}/today", headers=headers).json()
    assert all(not row["teacher_review_tags"] for row in plan["attempts"])
    assert client.get(comparison, headers=headers).status_code == 403
    report = client.get(report_url, headers=headers).json()
    assert (
        report["has_active_exam"]
        and report["answers"] == []
        and report["reading_avg"] is None
    )


def test_copy_content_creates_independent_owned_version(
    client: TestClient, db: Session, teachers, superuser_token_headers: dict[str, str]
) -> None:
    owner_headers, other_headers, owner = teachers
    source = client.post(
        "/api/v1/admin/passages",
        headers=owner_headers,
        json={"title": "School material", "text": "Frozen original content."},
    ).json()
    pid = uuid.UUID(source["id"])
    preview = client.get(f"/api/v1/admin/content/passage/{pid}", headers=other_headers)
    assert preview.status_code == 200 and preview.json()["text"] == source["text"]
    missing = client.get(
        f"/api/v1/admin/content/passage/{uuid.uuid4()}", headers=other_headers
    )
    assert missing.status_code == 404
    sentence = RepeatSentence(
        passage_id=pid,
        owner_id=owner.id,
        order_index=0,
        text="Original sentence",
        exam_settings={"answer_seconds": 20},
    )
    db.add(sentence)
    db.commit()
    result = client.post(
        f"/api/v1/admin/content/passage/{pid}/copy", headers=other_headers
    )
    assert result.status_code == 200, result.text
    copy = db.get(Passage, uuid.UUID(result.json()["id"]))
    assert copy is not None and copy.owner_id != owner.id and copy.copied_from_id == pid
    assert copy.slug != source["slug"]
    copied_sentence = db.exec(
        select(RepeatSentence).where(RepeatSentence.passage_id == copy.id)
    ).one()
    assert copied_sentence.copied_from_id == sentence.id
    assert copied_sentence.exam_settings == sentence.exam_settings
    assert copied_sentence.owner_id == copy.owner_id
    assert (
        client.put(
            f"/api/v1/admin/passages/{copy.id}",
            headers=other_headers,
            json={"text": "My changes"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/v1/admin/passages/{copy.id}",
            headers=owner_headers,
            json={"text": "Unauthorized"},
        ).status_code
        == 403
    )
    original = db.get(Passage, pid)
    assert original is not None
    db.refresh(original)
    assert original.text == "Frozen original content."
    detached = client.post(
        f"/api/v1/admin/content/repeat/{sentence.id}/copy", headers=other_headers
    ).json()
    detached_row = db.get(RepeatSentence, uuid.UUID(detached["id"]))
    assert detached_row is not None and detached_row.passage_id is None
