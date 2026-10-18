"""个人弱项诊断接口：漏词聚合 + 四维均值/最弱维度 + 四维趋势（模考遮罩同 trail 口径）。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import Attempt, AttemptItemType, AttemptStatus, PracticeSession
from tests.utils.credential import make_student


def _attempt(
    db: Session,
    student_id: uuid.UUID,
    session_id: uuid.UUID,
    item_type: str,
    *,
    days_ago: int,
    transcript: str | None = None,
    item_snapshot: dict | None = None,
    word_alignment: dict | None = None,
    rubric: dict | None = None,
) -> Attempt:
    row = Attempt(
        item_id=uuid.uuid4(),
        item_type=item_type,
        student_id=student_id,
        session_id=session_id,
        status=AttemptStatus.DONE,
        engine="mock",
        duration_s=12.0,
        audio_path="test.webm",
        transcript=transcript,
        item_snapshot=item_snapshot,
        word_alignment=word_alignment,
        rubric=rubric,
        overall=70,
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(row)
    return row


def test_diagnostics_aggregates_missed_words_and_dimensions(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    classroom = client.post(
        "/api/v1/classes",
        json={"class_size": 10},
        headers=superuser_token_headers,
    ).json()
    code = classroom["code"]
    made = make_student(db, client, code)
    headers = made["headers"]
    student_id = made["student"]["id"]

    from datetime import date

    session = PracticeSession(
        student_id=student_id,
        session_date=date.today(),
        mode="daily",
        classroom_id=classroom["id"],
        band="A2",
    )
    db.add(session)
    db.flush()
    sid = session.id
    # 朗读：词级对齐（green 读错 2 次、apples 漏读 1 次）
    for _ in range(2):
        _attempt(
            db,
            student_id,
            sid,
            AttemptItemType.PASSAGE,
            days_ago=1,
            transcript="i like gren apples",
            item_snapshot={"text": "I like green apples."},
            word_alignment={
                "words": [
                    {"start": 0, "end": 1, "text": "I", "status": "correct", "heard": None},
                    {"start": 2, "end": 6, "text": "like", "status": "correct", "heard": None},
                    {"start": 7, "end": 12, "text": "green", "status": "error", "heard": "gren"},
                    {"start": 13, "end": 19, "text": "apples", "status": "missing", "heard": None},
                ],
                "extras": [],
            },
        )
    # 旧作答回退：无对齐时用 item_text + transcript 现算（friendly 漏读）
    _attempt(
        db,
        student_id,
        sid,
        AttemptItemType.REPEAT,
        days_ago=30,
        transcript="dogs are",
        item_snapshot={"text": "Dogs are friendly."},
    )
    # 问答：四维 rubric（任务最弱）
    for _ in range(2):
        _attempt(
            db,
            student_id,
            sid,
            AttemptItemType.QUESTION,
            days_ago=2,
            transcript="i think reading is good",
            rubric={
                "status": "done",
                "fluency": 3,
                "vocabulary": 3,
                "grammar": 3,
                "task": 2,
                "mock_score": 5,
            },
        )
    _attempt(
        db,
        student_id,
        sid,
        AttemptItemType.QUESTION,
        days_ago=4,
        transcript="reading helps me learn",
        rubric={
            "status": "done",
            "fluency": 4,
            "vocabulary": 4,
            "grammar": 4,
            "task": 3,
            "mock_score": 7,
        },
    )
    db.commit()

    resp = client.get(f"/api/v1/classes/{code}/diagnostics/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["student_id"] == str(student_id)

    words = {w["word"]: w["count"] for w in data["top_missed_words"]}
    assert words.get("green") == 2  # error 计入漏词
    assert words.get("apples") == 2
    assert words.get("friendly") == 1  # 旧作答回退对齐
    assert data["dimension_count"] == 3
    assert data["dimension_means"]["fluency"] == pytest.approx(10 / 3, abs=0.1)
    assert data["weakest_dimension"] == "task"
    # 趋势：按时间升序，最多 14 点
    trend = data["dimension_trend"]
    assert len(trend) == 3
    assert trend[0]["task"] == 3 and trend[-1]["task"] == 2


def test_diagnostics_teacher_can_query_student(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    classroom = client.post(
        "/api/v1/classes",
        json={"class_size": 10},
        headers=superuser_token_headers,
    ).json()
    code = classroom["code"]
    made = make_student(db, client, code)
    student = made["student"]

    resp = client.get(
        f"/api/v1/classes/{code}/diagnostics/me",
        params={"student_id": str(student["id"])},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["student_id"] == str(student["id"])
    assert resp.json()["top_missed_words"] == []
