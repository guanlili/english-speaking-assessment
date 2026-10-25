"""大盘日快照：业务量回算 / 幂等 upsert / 回填 / performance 端点门与形状。"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.metrics_daily import backfill_history, upsert_daily_snapshot
from app.models import AdminMetricsDaily, Attempt, PracticeSession
from tests.utils.credential import make_student

tz = ZoneInfo(settings.PRACTICE_TZ)


def _purge(db: Session) -> None:
    db.exec(delete(Attempt))  # type: ignore[call-overload]
    db.exec(delete(PracticeSession))  # type: ignore[call-overload]
    db.exec(delete(AdminMetricsDaily))  # type: ignore[call-overload]
    db.commit()


def _attempt(db: Session, student_id: uuid.UUID, day: date, *, status: str, dur: float = 5.0) -> None:
    db.add(
        Attempt(
            item_type="question",
            item_id=uuid.uuid4(),
            student_id=student_id,
            audio_path="t.webm",
            duration_s=dur,
            status=status,
            created_at=datetime.combine(
                day, datetime.min.time().replace(hour=10), tz
            ),
        )
    )
    db.flush()


def test_daily_snapshot_business_and_upsert_idempotent(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    ada = make_student(db, client, classroom["code"], "Ada")
    today = datetime.now(tz).date()
    day = today - timedelta(days=1)

    ada_id = uuid.UUID(ada["student"]["id"])
    _attempt(db, ada_id, day, status="done", dur=5.0)
    _attempt(db, ada_id, day, status="done", dur=7.0)
    _attempt(db, ada_id, day, status="failed", dur=3.0)
    db.add(
        PracticeSession(
            classroom_id=uuid.UUID(classroom["id"]),
            student_id=ada_id,
            band="B1",
            session_date=day,
        )
    )
    db.commit()

    row = upsert_daily_snapshot(db, day)
    assert row.attempts == 3
    assert row.attempts_done == 2
    assert row.attempts_failed == 1
    assert row.active_students == 1
    assert row.sessions == 1
    assert row.asr_seconds == 15.0
    assert row.queue_max_age_s is None  # 回算不带峰值

    # 再写一次（带峰值）→ 覆盖业务量、补上峰值；日期幂等不建新行
    row2 = upsert_daily_snapshot(db, day, queue_max_age_s=42.0, pool_max_checked_out=3)
    assert row2.attempts == 3
    assert row2.queue_max_age_s == 42.0
    count = len(db.query(AdminMetricsDaily).all())
    assert count == 1


def test_backfill_only_missing_rows(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    ada = make_student(db, client, classroom["code"], "Ada")
    today = datetime.now(tz).date()
    day3 = today - timedelta(days=3)
    _attempt(db, uuid.UUID(ada["student"]["id"]), day3, status="done")

    db.commit()

    written = backfill_history(db, today)
    assert written == 3  # day3/day2/day1 各补一行
    row3 = db.get(AdminMetricsDaily, day3)
    assert row3 is not None and row3.attempts == 1
    assert db.get(AdminMetricsDaily, today - timedelta(days=2)).attempts == 0

    # 再跑一遍：全部已存在，零写入
    assert backfill_history(db, today) == 0


def test_performance_endpoint_gates_and_shape(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge(db)
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    upsert_daily_snapshot(db, yesterday, queue_max_age_s=10.0)

    # 401 / 403
    assert client.get("/api/v1/admin/dashboard/performance").status_code == 401
    from app import crud
    from app.models import UserCreate
    from tests.utils.utils import random_email, random_lower_string

    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    teacher = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert teacher.status_code == 200
    headers = {"Authorization": f"Bearer {teacher.json()['access_token']}"}
    assert (
        client.get(
            "/api/v1/admin/dashboard/performance", headers=headers
        ).status_code
        == 403
    )

    resp = client.get(
        "/api/v1/admin/dashboard/performance?days=7",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 实时快照与 /admin/metrics 同构
    assert {"scoring", "providers", "audio_storage", "db_pool"} <= set(
        body["realtime"]
    )
    assert "by_status" in body["realtime"]["scoring"]
    # 历史行形状
    assert [h["date"] for h in body["history"]] == [yesterday.isoformat()]
    assert body["history"][0]["queue_max_age_s"] == 10.0
    assert body["runtime_issues_today"] == 0
