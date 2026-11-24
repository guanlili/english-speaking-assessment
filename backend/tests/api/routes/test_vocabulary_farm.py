"""专注农场闭环测试：成长口径、收获入账、徽章账本、跨班连续与权限边界。

口径约束（设计稿 docs/vocabulary-pk-farm-design-20261122.md §4）：
- 只认任务练习 / 自主练习 / FSRS 复习的首答（attempt_no=1）；quiz 不计、重试不计。
- 每有效首答 +1，每日最多 30 点；成熟（≥20）可收获 +10 XP，每日农场 XP 上限 10。
- XP 写既有 student.xp；streak 不由农场推进/重置；徽章落既有 student_badge 表。
- 地块按登录账号跨班连续；历史班级作答与快照不被迁移或重写。
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app import crud
from app.models import (
    BADGE_FARM_FIRST_HARVEST,
    BADGE_FARM_HARVEST_7,
    HARVEST_XP,
    Student,
    StudentBadge,
    User,
    UserCreate,
    VocabFarmPlot,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularySession,
)
from app.services import vocabulary_farm as farm_service
from tests.utils.credential import join_as, make_student
from tests.utils.utils import random_email, random_lower_string

FARM = "/api/v1/classes/{code}/vocabulary/student/farm"
HARVEST = FARM + "/harvest"


def _login_teacher(db: Session, client: TestClient) -> tuple[User, dict[str, str]]:
    email, password = random_email(), random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _words(n: int, prefix: str) -> list[dict]:
    return [
        {
            "headword": f"{prefix}{i:02d}",
            "part_of_speech": "n.",
            "meaning_zh": f"{prefix}义{i}",
        }
        for i in range(1, n + 1)
    ]


def _make_book(
    client: TestClient,
    headers: dict[str, str],
    classroom_id: str,
    words: list[dict],
    title: str,
) -> dict:
    resp = client.post(
        "/api/v1/vocabulary/books",
        json={
            "title": title,
            "scope": "classroom",
            "classroom_id": classroom_id,
            "words": words,
            "confirm_reviewed": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    word_ids: list[str],
    **extra: object,
) -> dict:
    body: dict = {"word_ids": word_ids, "prompt_types": ["meaning"]}
    body.update(extra)
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments",
        json=body,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_session(client: TestClient, headers: dict[str, str], code: str) -> str:
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions", json={}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def _answer(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    answer: str,
) -> dict:
    resp = client.post(
        f"/api/v1/vocabulary/sessions/{session_id}/answers",
        json={
            "item_index": item_index,
            "prompt_type": "meaning",
            "answer": answer,
        },
        headers=headers,
    )
    return resp.json() | {"_status": resp.status_code}


def _fetch_farm(
    client: TestClient, headers: dict[str, str], code: str
) -> tuple[int, dict]:
    resp = client.get(FARM.format(code=code), headers=headers)
    return resp.status_code, resp.json()


def _student_row(db: Session, user_id: uuid.UUID) -> Student:
    student = db.exec(
        select(Student).where(Student.user_id == user_id)  # type: ignore[arg-type]
    ).first()
    assert student is not None
    return student


def _plot(db: Session, user_id: uuid.UUID) -> VocabFarmPlot | None:
    return db.exec(
        select(VocabFarmPlot).where(VocabFarmPlot.user_id == user_id)  # type: ignore[arg-type]
    ).first()


# ── 成长口径：首答计分，重试 / quiz 不计 ──────────────────────────────


def test_first_answer_growth_retry_not_counted(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(
        client, teacher_headers, classroom["id"], _words(3, "r"), "r-book"
    )
    word_ids = [w["id"] for w in book["words"]]
    student = make_student(db, client, classroom["code"], "重试同学")
    _publish(client, teacher_headers, classroom["code"], word_ids)

    session_id = _start_session(client, student["headers"], classroom["code"])
    # 首答答对 item 0
    first = _answer(
        client, student["headers"], session_id, 0, book["words"][0]["headword"]
    )
    assert first["_status"] == 200, first
    assert first["attempt_no"] == 1
    # 同题重试（attempt_no=2）：不计入农场成长
    retry = _answer(client, student["headers"], session_id, 0, "wrong-retry")
    assert retry["_status"] == 200, retry
    assert retry["attempt_no"] == 2

    _status, farm = _fetch_farm(client, student["headers"], classroom["code"])
    assert _status == 200, farm
    assert farm["today_points"] == 1
    assert farm["growth_points"] == 1


def test_quiz_answers_do_not_grow_plot(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(
        client, teacher_headers, classroom["id"], _words(3, "q"), "q-book"
    )
    word_ids = [w["id"] for w in book["words"]]
    student = make_student(db, client, classroom["code"], "测验同学")
    _publish(
        client,
        teacher_headers,
        classroom["code"],
        word_ids,
        mode="quiz",
        duration_minutes=30,
    )

    session_id = _start_session(client, student["headers"], classroom["code"])
    ans = _answer(
        client, student["headers"], session_id, 0, book["words"][0]["headword"]
    )
    assert ans["_status"] == 200, ans

    # quiz 不产生农场地块成长记录（plot 可惰性创建，但点数为 0）
    plot = _plot(db, student["user"].id)
    if plot is not None:
        assert plot.growth_points == 0
        assert plot.today_points == 0
    _status, farm = _fetch_farm(client, student["headers"], classroom["code"])
    assert _status == 200, farm
    assert farm["today_points"] == 0
    assert farm["growth_points"] == 0


# ── 每日上限与跨日重置 ──────────────────────────────────────────────


def test_daily_growth_cap_and_cross_day_reset(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"], "上限同学")
    user_id = student["user"].id

    for _ in range(30):
        assert farm_service.record_valid_first_answer(db, user_id=user_id) is True
    plot = _plot(db, user_id)
    assert plot is not None
    assert plot.today_points == 30
    assert plot.growth_points == 30
    # 第 31 条：当日上限拒收，不再增长
    assert farm_service.record_valid_first_answer(db, user_id=user_id) is False
    db.refresh(plot)
    assert plot.today_points == 30
    assert plot.growth_points == 30

    # 跨自然日：昨日计数清零，新一天重新计
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    plot.last_points_date = yesterday
    db.add(plot)
    db.commit()
    assert farm_service.record_valid_first_answer(db, user_id=user_id) is True
    db.refresh(plot)
    assert plot.today_points == 1
    assert plot.growth_points == 31


# ── 收获：成熟门禁、XP 入账、日上限、幂等 ────────────────────────────


def _mature_plot(db: Session, user_id: uuid.UUID, points: int = 20) -> VocabFarmPlot:
    plot = farm_service._get_or_create_plot(db, user_id)
    plot.growth_points = points
    db.add(plot)
    db.commit()
    db.refresh(plot)
    return plot


def test_harvest_requires_maturity(client: TestClient, db: Session) -> None:
    _, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"], "未成熟同学")
    _mature_plot(db, student["user"].id, points=12)

    resp = client.post(
        HARVEST.format(code=classroom["code"]), headers=student["headers"]
    )
    assert resp.status_code == 422, resp.text
    plot = _plot(db, student["user"].id)
    assert plot is not None
    assert plot.harvest_count == 0


def test_harvest_grants_xp_deducts_points_and_idempotent(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"], "收获同学")
    student_row = _student_row(db, student["user"].id)
    before_xp = student_row.xp or 0
    _mature_plot(db, student["user"].id, points=25)

    resp = client.post(
        HARVEST.format(code=classroom["code"]), headers=student["headers"]
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["harvested"] is True
    assert result["xp_gained"] == HARVEST_XP
    assert result["xp"] == before_xp + HARVEST_XP
    # 扣除 20 点、剩余 5 点保留
    assert result["growth_points"] == 5
    assert result["harvest_count"] == 1

    # 幂等：收获后未成熟，重复请求 422，不二次入账
    repeat = client.post(
        HARVEST.format(code=classroom["code"]), headers=student["headers"]
    )
    assert repeat.status_code == 422, repeat.text
    db.refresh(student_row)
    assert student_row.xp == before_xp + HARVEST_XP

    # 今日农场 XP 已达 10 上限：即便再次成熟，收获也被拒收
    _mature_plot(db, student["user"].id, points=20)
    capped = client.post(
        HARVEST.format(code=classroom["code"]), headers=student["headers"]
    )
    assert capped.status_code == 422, capped.text
    db.refresh(student_row)
    assert student_row.xp == before_xp + HARVEST_XP


def test_farm_does_not_touch_streak(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"], "连胜同学")
    student_row = _student_row(db, student["user"].id)
    student_row.streak_days = 3
    student_row.last_practice_date = date.today()
    db.add(student_row)
    db.commit()

    _mature_plot(db, student["user"].id, points=20)
    resp = client.post(
        HARVEST.format(code=classroom["code"]), headers=student["headers"]
    )
    assert resp.status_code == 200, resp.text

    db.refresh(student_row)
    assert student_row.streak_days == 3
    assert student_row.last_practice_date == date.today()


# ── 徽章：落既有 student_badge 表 ─────────────────────────────────────


def test_farm_badges_persist_in_existing_badge_table(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"], "徽章同学")
    user_id = student["user"].id
    student_row = _student_row(db, user_id)

    def _reset_daily_xp() -> None:
        # 模拟跨自然日：当日农场 XP 额度重置（测试态，不改生产口径）
        plot = farm_service._get_or_create_plot(db, user_id)
        plot.today_farm_xp = 0
        plot.last_farm_xp_date = datetime.now(UTC).date() - timedelta(days=1)
        db.add(plot)
        db.commit()

    # 前 6 次收获（跨日重置 XP 额度）：只拿首次徽章
    for _ in range(6):
        _reset_daily_xp()
        _mature_plot(db, user_id, points=20)
        resp = client.post(
            HARVEST.format(code=classroom["code"]), headers=student["headers"]
        )
        assert resp.status_code == 200, resp.text
    keys = {
        b.badge_key
        for b in db.exec(
            select(StudentBadge).where(StudentBadge.student_id == student_row.id)  # type: ignore[arg-type]
        ).all()
    }
    assert BADGE_FARM_FIRST_HARVEST in keys
    assert BADGE_FARM_HARVEST_7 not in keys

    # 第 7 次收获：累计 7 次徽章落库
    _reset_daily_xp()
    _mature_plot(db, user_id, points=20)
    resp = client.post(
        HARVEST.format(code=classroom["code"]), headers=student["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert BADGE_FARM_HARVEST_7 in resp.json()["newly_awarded"]
    keys = {
        b.badge_key
        for b in db.exec(
            select(StudentBadge).where(StudentBadge.student_id == student_row.id)  # type: ignore[arg-type]
        ).all()
    }
    assert BADGE_FARM_HARVEST_7 in keys


# ── 跨班连续、历史数据不变、权限边界 ──────────────────────────────────


def test_plot_continuous_across_classes_and_history_untouched(
    client: TestClient, db: Session
) -> None:
    teacher_a, headers_a = _login_teacher(db, client)
    room_a = _create_classroom(client, headers_a)
    teacher_b, headers_b = _login_teacher(db, client)
    room_b = _create_classroom(client, headers_b)

    book = _make_book(client, headers_a, room_a["id"], _words(3, "c"), "c-book")
    word_ids = [w["id"] for w in book["words"]]
    student = make_student(db, client, room_a["code"], "跨班同学")
    _publish(client, headers_a, room_a["code"], word_ids)

    session_id = _start_session(client, student["headers"], room_a["code"])
    ans = _answer(
        client, student["headers"], session_id, 0, book["words"][0]["headword"]
    )
    assert ans["_status"] == 200, ans

    # 同一账号加入 B 班：地块跨班连续，点数延续
    join_as(client, room_b["code"], student["user"])
    _status, farm_b = _fetch_farm(client, student["headers"], room_b["code"])
    assert _status == 200, farm_b
    plot_a = _plot(db, student["user"].id)
    assert plot_a is not None
    assert farm_b["growth_points"] == plot_a.growth_points
    assert farm_b["today_points"] == plot_a.today_points

    # 历史班级作答与快照不被迁移或重写（跨班后同一账号可能有多条档案，
    # 按用户全部档案 ID 归集会话，避免档案返回顺序造成误判）
    student_rows = db.exec(
        select(Student).where(
            Student.user_id == student["user"].id  # type: ignore[arg-type]
        )
    ).all()
    student_ids = {row.id for row in student_rows}
    student_sessions = db.exec(
        select(VocabularySession).where(
            col(VocabularySession.student_id).in_(student_ids)  # type: ignore[call-overload]
        )
    ).all()
    session_ids = {s.id for s in student_sessions}
    answers = [
        a
        for a in db.exec(select(VocabularyAnswer)).all()
        if a.session_id in session_ids
    ]
    assert len(answers) == 1
    assert answers[0].word_id == uuid.UUID(word_ids[0])
    # B 班不存在该任务快照
    room_b_assignments = db.exec(
        select(VocabularyAssignment).where(
            VocabularyAssignment.classroom_id == uuid.UUID(room_b["id"])  # type: ignore[arg-type]
        )
    ).all()
    assert room_b_assignments == []


def test_cross_classroom_outsider_404(client: TestClient, db: Session) -> None:
    teacher_a, headers_a = _login_teacher(db, client)
    room_a = _create_classroom(client, headers_a)
    teacher_b, headers_b = _login_teacher(db, client)
    room_b = _create_classroom(client, headers_b)
    outsider = make_student(db, client, room_b["code"], "外班同学")

    resp = client.get(FARM.format(code=room_a["code"]), headers=outsider["headers"])
    assert resp.status_code == 404, resp.text


def test_teacher_cannot_access_farm_student_endpoint(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    room = _create_classroom(client, headers)
    resp = client.get(FARM.format(code=room["code"]), headers=headers)
    assert resp.status_code == 403, resp.text
