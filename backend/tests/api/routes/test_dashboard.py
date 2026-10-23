"""管理员平台大盘：superuser 门 + 速览/趋势/课堂排行的口径断言。"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import crud
from app.core.config import settings
from app.models import Attempt, PracticeSession, UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

PATHS = ("overview", "usage", "content")


def _purge_activity(db: Session) -> None:
    """大盘是全平台聚合，先清其他模块遗留的作答/会话，才能断言精确值。"""
    db.exec(delete(Attempt))  # type: ignore[call-overload]
    db.exec(delete(PracticeSession))  # type: ignore[call-overload]
    db.commit()


def _add_attempt(
    db: Session,
    student_id: uuid.UUID,
    *,
    item_type: str,
    created_at: datetime,
    status: str = "done",
    overall: int | None = None,
    completeness: int | None = None,
    session_id: uuid.UUID | None = None,
) -> None:
    db.add(
        Attempt(
            item_type=item_type,
            item_id=uuid.uuid4(),
            student_id=student_id,
            session_id=session_id,
            audio_path="t.webm",
            duration_s=3.0,
            status=status,
            created_at=created_at,
            overall=overall,
            completeness=completeness,
        )
    )
    db.flush()


def _add_session(
    db: Session,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    session_date: date,
    *,
    exam: bool = False,
    issue: str | None = None,
) -> PracticeSession:
    row = PracticeSession(
        classroom_id=classroom_id,
        student_id=student_id,
        band="B1",
        session_date=session_date,
        exam_started_at=datetime.now(ZoneInfo(settings.PRACTICE_TZ)) if exam else None,
        runtime_issue=issue,
    )
    db.add(row)
    db.flush()
    return row


def test_dashboard_requires_superuser(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # 无 token 401；教师 403（不触发登出的权限语义）；superuser 200。
    # 测试库没有种子教师——真建一个账号登录，断言必须实际执行。
    for path in PATHS:
        assert client.get(f"/api/v1/admin/dashboard/{path}").status_code == 401, path
    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    teacher = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert teacher.status_code == 200, teacher.text
    headers = {"Authorization": f"Bearer {teacher.json()['access_token']}"}
    for path in PATHS:
        resp = client.get(f"/api/v1/admin/dashboard/{path}", headers=headers)
        assert resp.status_code == 403, path
    for path in PATHS:
        resp = client.get(
            f"/api/v1/admin/dashboard/{path}", headers=superuser_token_headers
        )
        assert resp.status_code == 200, path


def test_dashboard_overview_and_usage_semantics(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge_activity(db)
    class_a = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    class_b = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    ada = make_student(db, client, class_a["code"], "Ada")
    ben = make_student(db, client, class_a["code"], "Ben")
    cal = make_student(db, client, class_b["code"], "Cal")

    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    old_day = today - timedelta(days=20)

    def at(day: date, hour: int = 10) -> datetime:
        return datetime.combine(
            day,
            datetime.min.time().replace(hour=hour),
            tz,  # type: ignore[arg-type]
        )

    a_id, b_id = uuid.UUID(class_a["id"]), uuid.UUID(class_b["id"])
    ada_id = uuid.UUID(ada["student"]["id"])
    ben_id = uuid.UUID(ben["student"]["id"])
    cal_id = uuid.UUID(cal["student"]["id"])

    # 昨天（A 班 Ada）：两问答 + 一跟读，全会话
    ps_ada = _add_session(db, a_id, ada_id, yesterday)
    _add_attempt(
        db,
        ada_id,
        item_type="question",
        created_at=at(yesterday, 9),
        overall=70,
        session_id=ps_ada.id,
    )
    _add_attempt(
        db,
        ada_id,
        item_type="question",
        created_at=at(yesterday, 10),
        overall=80,
        session_id=ps_ada.id,
    )
    _add_attempt(
        db,
        ada_id,
        item_type="repeat",
        created_at=at(yesterday, 11),
        completeness=90,
        session_id=ps_ada.id,
    )
    # 今天（A 班 Ben）：一条问答完成 + 一条跟读失败；会话带模考与异常标记
    ps_ben = _add_session(db, a_id, ben_id, today, exam=True, issue="mic")
    _add_attempt(
        db,
        ben_id,
        item_type="question",
        created_at=at(today, 9),
        overall=60,
        session_id=ps_ben.id,
    )
    _add_attempt(
        db,
        ben_id,
        item_type="repeat",
        created_at=at(today, 10),
        status="failed",
        session_id=ps_ben.id,
    )
    # 20 天前（B 班 Cal）：一条问答 → 7 天外、30 天内，构成沉默课堂
    ps_cal = _add_session(db, b_id, cal_id, old_day)
    _add_attempt(
        db,
        cal_id,
        item_type="question",
        created_at=at(old_day, 9),
        overall=50,
        session_id=ps_cal.id,
    )
    db.commit()

    # ── overview：今日卡与 7 天区间卡 ──────────────────────────
    resp = client.get(
        "/api/v1/admin/dashboard/overview?days=7", headers=superuser_token_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 7
    assert body["range_start"] == (today - timedelta(days=6)).isoformat()
    assert body["today"] == {
        "attempts": 2,
        "active_students": 1,
        "active_classrooms": 1,
        "scored_done": 1,
        "scored_failed": 1,
        "exam_sessions": 1,
        "runtime_issues": 1,
    }
    assert body["range"] == {
        "attempts": 5,
        "active_students": 2,
        "active_classrooms": 1,
        "scored_done": 4,
        "scored_failed": 1,
        "exam_sessions": 1,
        "runtime_issues": 1,
    }

    # ── usage：日点、题型分布、课堂排行、沉默课堂 ───────────────
    resp = client.get(
        "/api/v1/admin/dashboard/usage?days=30", headers=superuser_token_headers
    )
    assert resp.status_code == 200, resp.text
    usage = resp.json()
    points = {p["date"]: p for p in usage["points"]}
    assert set(points) == {
        old_day.isoformat(),
        yesterday.isoformat(),
        today.isoformat(),
    }

    y, t = points[yesterday.isoformat()], points[today.isoformat()]
    assert y["attempts"] == 3
    assert y["active_students"] == 1
    assert y["active_classrooms"] == 1
    assert y["question_avg"] == 75.0
    assert y["repeat_completeness_avg"] == 90.0
    assert y["scored_failed"] == 0
    assert t["attempts"] == 2
    assert t["attempts_question"] == 1
    assert t["attempts_repeat"] == 1
    assert t["question_avg"] == 60.0
    # 跟读失败：完整度均分无值（均分只算 DONE）
    assert t["repeat_completeness_avg"] is None
    assert t["scored_failed"] == 1

    assert usage["item_distribution"] == {
        "passage": 0,
        "repeat": 2,
        "question": 4,
    }

    rows = {r["code"]: r for r in usage["classrooms"]}
    row_a, row_b = rows[class_a["code"]], rows[class_b["code"]]
    assert row_a["students"] == 2
    assert row_a["attempts"] == 5  # 7 天窗口外的 20 天前作答不在此列
    assert row_a["attempts_all"] == 5
    assert row_a["avg_score"] == 70.0
    assert row_a["silent_days"] == 0
    assert row_b["attempts"] == 1  # 30 天窗口把 20 天前的作答计入
    assert row_b["attempts_all"] == 1
    assert row_b["silent_days"] == 20
    # 排序：区间作答数降序
    assert usage["classrooms"][0]["code"] == class_a["code"]

    codes = [r["code"] for r in usage["silent_classrooms"]]
    assert codes == [class_b["code"]]

    # ── content：资产计数冒烟 ──────────────────────────────────
    resp = client.get(
        "/api/v1/admin/dashboard/content", headers=superuser_token_headers
    )
    assert resp.status_code == 200, resp.text
    content = resp.json()
    assert content["classrooms_total"] >= 2
    assert content["classrooms_active"] >= 2
    # 测试库不走迁移，种子超管的 role 停在默认 teacher（生产由迁移双写 admin）
    assert content["users_teacher"] >= 1
    assert content["student_accounts"] >= 3
    assert content["student_profiles"] >= 3


def test_dashboard_usage_short_range_keeps_recent_window(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """days<14 时近 14 天窗口比所选区间更早：区间零作答但近窗活跃的课堂
    必须仍在榜且不算沉默。锁住课堂排行 A 查询的 trim_ts=min(区间,近窗)
    分支——若只按区间裁剪 join，10 天前的作答进不了近窗计数，该课堂会被
    误判为沉默。"""
    _purge_activity(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    eve = make_student(db, client, classroom["code"], "Eve")

    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    ten_days_ago = today - timedelta(days=10)
    ps = _add_session(
        db,
        uuid.UUID(classroom["id"]),
        uuid.UUID(eve["student"]["id"]),
        ten_days_ago,
    )
    _add_attempt(
        db,
        uuid.UUID(eve["student"]["id"]),
        item_type="question",
        created_at=datetime.combine(
            ten_days_ago, datetime.min.time().replace(hour=10), tz
        ),
        overall=65,
        session_id=ps.id,
    )
    db.commit()

    resp = client.get(
        "/api/v1/admin/dashboard/usage?days=7", headers=superuser_token_headers
    )
    assert resp.status_code == 200, resp.text
    usage = resp.json()
    # 区间（7 天）不含 10 天前的作答；课堂仍在榜、近窗活跃 → 不算沉默
    rows = {r["code"]: r for r in usage["classrooms"]}
    row = rows[classroom["code"]]
    assert row["attempts"] == 0
    assert row["attempts_all"] == 1
    assert [r["code"] for r in usage["silent_classrooms"]] == []
    # 趋势点同样不含窗口外作答
    assert usage["points"] == []

    resp = client.get(
        "/api/v1/admin/dashboard/overview?days=7", headers=superuser_token_headers
    )
    assert resp.json()["range"]["attempts"] == 0
