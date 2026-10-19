"""教师端班级趋势：日聚合（活跃学生/问答均分/跟读完整度）。"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Attempt, Classroom, PracticeSession
from tests.utils.credential import make_student


def _add_done_attempt(
    db: Session,
    student_id: uuid.UUID,
    *,
    item_type: str,
    created_at: datetime,
    overall: int | None = None,
    completeness: int | None = None,
) -> None:
    db.add(
        Attempt(
            item_type=item_type,
            item_id=uuid.uuid4(),
            student_id=student_id,
            session_id=None,
            audio_path="test.wav",
            duration_s=4,
            status="done",
            created_at=created_at,
            overall=overall,
            completeness=completeness,
        )
    )
    db.flush()


def test_class_trend_groups_by_practice_day_for_teacher(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    code = classroom["code"]
    ada = make_student(db, client, code, "Ada")
    ben = make_student(db, client, code, "Ben")
    row = db.get(Classroom, uuid.UUID(classroom["id"]))
    assert row is not None

    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)

    # 昨天：Ada 两条问答 + 一条跟读；Ben 一条问答（不同日）→ 只算 Ben 当天
    def at_day(day, hour=10):
        return datetime.combine(day, datetime.min.time().replace(hour=hour), tz)

    _add_done_attempt(
        db, uuid.UUID(ada["student"]["id"]), item_type="question",
        created_at=at_day(yesterday, 9), overall=70,
    )
    _add_done_attempt(
        db, uuid.UUID(ada["student"]["id"]), item_type="question",
        created_at=at_day(yesterday, 10), overall=80,
    )
    _add_done_attempt(
        db, uuid.UUID(ada["student"]["id"]), item_type="repeat",
        created_at=at_day(yesterday, 11), completeness=90,
    )
    # 今天：Ben 一条问答（验证活跃学生去重与当日桶）
    _add_done_attempt(
        db, uuid.UUID(ben["student"]["id"]), item_type="question",
        created_at=at_day(today, 9), overall=60,
    )
    # 非 done（queued）不计入
    db.add(
        Attempt(
            item_type="question",
            item_id=uuid.uuid4(),
            student_id=uuid.UUID(ada["student"]["id"]),
            session_id=None,
            audio_path="test.wav",
            duration_s=4,
            status="queued",
            created_at=at_day(yesterday, 12),
            overall=95,
        )
    )
    db.flush()
    db.commit()

    resp = client.get(f"/api/v1/classes/{code}/trend?days=14", headers=superuser_token_headers)
    assert resp.status_code == 200, resp.text
    days = resp.json()
    assert [d["date"] for d in days] == [str(yesterday), str(today)]
    y, t = days[0], days[1]
    # 昨天：2 位学生 DONE 去重 → 1；问答均分 (70+80)/2=75；完整度 90
    assert y["active_students"] == 1
    assert y["question_attempts"] == 2
    assert y["question_avg"] == 75
    assert y["repeat_completeness_avg"] == 90
    # 今天：Ben 1 条问答
    assert t["active_students"] == 1
    assert t["question_attempts"] == 1
    assert t["question_avg"] == 60
    assert t["repeat_completeness_avg"] is None


def test_class_trend_requires_teacher(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 2}, headers=superuser_token_headers
    ).json()
    code = classroom["code"]
    stu = make_student(db, client, code, "Stu")
    resp = client.get(
        f"/api/v1/classes/{code}/trend", headers=stu["headers"]
    )
    assert resp.status_code == 403
