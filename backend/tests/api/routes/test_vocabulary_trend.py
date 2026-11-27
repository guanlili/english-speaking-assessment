"""教师跨任务 / 时间趋势（#517 C）后端测试。

口径守点：
- 周一起 / 1 日起，PRACTICE_TZ；含 anchor 周期在内的最近 N 个周期，升序；
- 完成率分母 = 周期内任务目标名单中的当前在册学生；首轮首答覆盖全部题位
  才算完成（不要求全对）；部分作答 / 未开始不计完成；
- 首答只统计 kind=task、round_no=1、attempt_no=1；无作答正确率 null；
- 掌握度分段与现有 mastery 同阈值（<60 / 60–85 / >85 / 无首答）；
- due_unreviewed 为当前状态回算；book_id / prompt_type 筛选同步缩小词条全集；
- 权限：非本班教师 403；课堂不存在 404；vocabulary 模块关闭 403。
"""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.models import (
    Classroom,
    TenantModule,
    User,
    UserCreate,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularyReviewState,
    VocabularySession,
)
from app.services import vocabulary_trend
from tests.utils.credential import make_student, student_db_row
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
TREND = "/api/v1/classes/{code}/vocabulary/trend"
TREND_CSV = "/api/v1/classes/{code}/vocabulary/trend.csv"

WORDS_2 = [
    {"headword": "apple", "part_of_speech": "n.", "meaning_zh": "苹果"},
    {"headword": "banana", "part_of_speech": "n.", "meaning_zh": "香蕉"},
]

WORDS_4 = [
    {"headword": "alpha", "part_of_speech": "n.", "meaning_zh": "甲"},
    {"headword": "bravo", "part_of_speech": "n.", "meaning_zh": "乙"},
    {"headword": "charlie", "part_of_speech": "n.", "meaning_zh": "丙"},
    {"headword": "delta", "part_of_speech": "n.", "meaning_zh": "丁"},
]


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


def _make_public_book(
    client: TestClient,
    admin_headers: dict[str, str],
    words: list[dict],
    title: str = "趋势公共词库",
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": title,
            "scope": "public",
            "words": words,
            "confirm_reviewed": True,
        },
        headers=admin_headers,
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
    body: dict[str, object] = {"word_ids": word_ids, "prompt_types": ["meaning"]}
    body.update(extra)
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments", json=body, headers=headers
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
        f"{VOCAB}/sessions/{session_id}/answers",
        json={"item_index": item_index, "prompt_type": "meaning", "answer": answer},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _backdate_assignment(db: Session, assignment_id: str, days_old: int) -> None:
    assignment = db.get(VocabularyAssignment, uuid.UUID(assignment_id))
    assert assignment is not None
    assignment.published_at = datetime.now(UTC) - timedelta(days=days_old)
    db.add(assignment)
    db.commit()


def _seed_answer(
    db: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment_id: uuid.UUID,
    word: dict,
    days_old: int,
    is_correct: bool,
    prompt_type: str = "meaning",
    item_index: int = 0,
) -> None:
    """直插一条历史任务轮首答（用于周期 / 筛选 / 分段口径校验）。

    同一（任务, 学生）首轮会话复用，避免会话唯一索引冲突；多条首答用不同
    item_index 落同一会话。
    """
    now = datetime.now(UTC)
    session = db.exec(
        select(VocabularySession).where(
            VocabularySession.assignment_id == assignment_id,  # type: ignore[arg-type]
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            VocabularySession.round_no == 1,
        )
    ).first()
    if session is None:
        session = VocabularySession(
            classroom_id=classroom_id,
            student_id=student_id,
            assignment_id=assignment_id,
            kind="task",
            round_no=1,
            status="submitted",
            started_at=now - timedelta(days=days_old),
            submitted_at=now - timedelta(days=days_old),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    db.add(
        VocabularyAnswer(
            session_id=session.id,
            item_index=item_index,
            attempt_no=1,
            prompt_type=prompt_type,
            answer_raw=word["headword"],
            answer_normalized=word["headword"].casefold(),
            is_correct=is_correct,
            word_id=uuid.UUID(word["id"]),
            headword=word["headword"],
            meaning_zh=word["meaning_zh"],
            answered_at=now - timedelta(days=days_old),
        )
    )
    db.commit()


def _report(
    db: Session,
    classroom: Any,
    *,
    granularity: str = "month",
    periods: int = 3,
    anchor=None,
    book_id: uuid.UUID | None = None,
    prompt_type: str | None = None,
):
    return vocabulary_trend.build_trend_report(
        db,
        classroom=classroom,
        granularity=granularity,
        periods=periods,
        anchor=anchor,
        book_id=book_id,
        prompt_type=prompt_type,
    )


# ── 基础聚合 ────────────────────────────────────────────────────────


def test_trend_current_period_completion_and_bands(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    student_a = make_student(db, client, code, "完成者")
    student_b = make_student(db, client, code, "进行者")
    make_student(db, client, code, "未开始者")

    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    _publish(client, headers, code, word_ids)

    # A 两题全对完成；B 只答第一题且拼错；C 未开始
    session_a = _start_session(client, student_a["headers"], code)
    _answer(client, student_a["headers"], session_a, 0, "apple")
    _answer(client, student_a["headers"], session_a, 1, "banana")
    session_b = _start_session(client, student_b["headers"], code)
    _answer(client, student_b["headers"], session_b, 0, "aple")

    resp = client.get(
        TREND.format(code=code),
        params={"granularity": "month", "periods": 3},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["teaching_reference"] is True
    assert report["granularity"] == "month"
    assert len(report["items"]) == 3

    current = report["items"][-1]
    assert current["assigned_targets"] == 3
    assert current["completed_targets"] == 1
    assert current["completion_rate"] == 33
    # A 两题对 + B 第一题错：首答 3，正确 2
    assert current["first_answered"] == 3
    assert current["first_correct"] == 2
    assert current["first_accuracy"] == 67
    # apple：2 答 1 对 = 50% 低；banana：1 答 1 对 = 100% 高
    assert current["low_count"] == 1
    assert current["high_count"] == 1
    assert current["mid_count"] == 0
    assert current["no_data_count"] == 0

    # 历史空周期：完成率 / 正确率为 null，不写 0%
    past = report["items"][0]
    assert past["assigned_targets"] == 0
    assert past["completed_targets"] == 0
    assert past["completion_rate"] is None
    assert past["first_answered"] == 0
    assert past["first_accuracy"] is None


def test_trend_week_backdated_assignment_lands_previous_week(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    make_student(db, client, code, "学生甲")

    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)
    _backdate_assignment(db, assignment["id"], days_old=10)

    classroom_row = db.get(Classroom, uuid.UUID(classroom["id"]))
    report = _report(db, classroom_row, granularity="week", periods=4)
    assert len(report.items) == 4
    # 10 天前的任务落在其所属周；当前周无任务，且恰好一个非空周期
    non_empty = [p for p in report.items if p.assigned_targets == 1]
    assert len(non_empty) == 1
    assert report.items[-1].assigned_targets == 0
    assert non_empty[0].completed_targets == 0
    assert non_empty[0].completion_rate == 0


def test_trend_month_backdated_assignment_lands_previous_month(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    make_student(db, client, code, "学生甲")

    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    assignment = _publish(client, headers, code, [w["id"] for w in book["words"]])
    _backdate_assignment(db, assignment["id"], days_old=40)

    classroom_row = db.get(Classroom, uuid.UUID(classroom["id"]))
    report = _report(db, classroom_row, granularity="month", periods=3)
    assert report.items[-1].assigned_targets == 0
    assert report.items[-2].assigned_targets == 1


def test_trend_periods_limit_and_granularity_validation(
    client: TestClient, db: Session
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    ok = client.get(
        TREND.format(code=code),
        params={"granularity": "week", "periods": 24},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["items"]) == 24

    too_many = client.get(
        TREND.format(code=code),
        params={"granularity": "week", "periods": 25},
        headers=headers,
    )
    assert too_many.status_code == 422

    bad_granularity = client.get(
        TREND.format(code=code),
        params={"granularity": "year"},
        headers=headers,
    )
    assert bad_granularity.status_code == 422


# ── 筛选 ────────────────────────────────────────────────────────────


def test_trend_book_id_filter(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    make_student(db, client, code, "学生甲")

    book_a = _make_public_book(client, superuser_token_headers, WORDS_2, "甲库")
    book_b = _make_public_book(client, superuser_token_headers, WORDS_4[:2], "乙库")
    _publish(client, headers, code, [w["id"] for w in book_a["words"]])
    _publish(client, headers, code, [w["id"] for w in book_b["words"]])

    classroom_row = db.get(Classroom, uuid.UUID(classroom["id"]))
    all_report = _report(db, classroom_row, granularity="month", periods=2)
    current_all = all_report.items[-1]
    # 两本库各 1 个目标 → 2 个目标；词条全集 4 个
    assert current_all.assigned_targets == 2

    report_a = _report(
        db,
        classroom_row,
        granularity="month",
        periods=2,
        book_id=uuid.UUID(book_a["id"]),
    )
    current_a = report_a.items[-1]
    assert current_a.assigned_targets == 1
    # 甲库词条全集 2 个
    assert (
        current_a.low_count
        + current_a.mid_count
        + current_a.high_count
        + current_a.no_data_count
        == 2
    )


def test_trend_prompt_type_filter(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "学生甲")
    student_row = student_db_row(db, student["student"]["id"])
    assert student_row is not None

    cloze_words = [
        {
            "headword": "apple",
            "part_of_speech": "n.",
            "meaning_zh": "苹果",
            "example_en": "I eat an apple every day.",
        },
        {
            "headword": "banana",
            "part_of_speech": "n.",
            "meaning_zh": "香蕉",
            "example_en": "A ripe banana is yellow.",
        },
    ]
    book = _make_public_book(client, superuser_token_headers, cloze_words)
    assignment = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments",
        json={
            "word_ids": [w["id"] for w in book["words"]],
            "prompt_types": ["meaning", "cloze"],
        },
        headers=headers,
    )
    assert assignment.status_code == 200, assignment.text
    assignment_id = uuid.UUID(assignment.json()["id"])
    # 直插一条 meaning 首答、一条 cloze 首答
    _seed_answer(
        db,
        classroom_id=uuid.UUID(classroom["id"]),
        student_id=student_row.id,
        assignment_id=assignment_id,
        word=book["words"][0],
        days_old=0,
        is_correct=True,
        prompt_type="meaning",
    )
    _seed_answer(
        db,
        classroom_id=uuid.UUID(classroom["id"]),
        student_id=student_row.id,
        assignment_id=assignment_id,
        word=book["words"][1],
        days_old=0,
        is_correct=False,
        prompt_type="cloze",
        item_index=1,
    )

    classroom_row = db.get(Classroom, uuid.UUID(classroom["id"]))
    all_report = _report(db, classroom_row, granularity="month", periods=2)
    assert all_report.items[-1].first_answered == 2

    cloze_report = _report(
        db, classroom_row, granularity="month", periods=2, prompt_type="cloze"
    )
    # 只保留 cloze 首答：1 答 0 对；meaning 首答被筛掉
    assert cloze_report.items[-1].first_answered == 1
    assert cloze_report.items[-1].first_correct == 0


# ── 完成口径：名单 / 部分作答 ──────────────────────────────────────


def test_trend_completion_roster_and_partial_not_done(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    student_a = make_student(db, client, code, "分组甲")
    student_b = make_student(db, client, code, "分组乙")
    late = make_student(db, client, code, "迟到者")

    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    student_a_row = student_db_row(db, student_a["student"]["id"])
    student_b_row = student_db_row(db, student_b["student"]["id"])
    assert student_a_row is not None
    assert student_b_row is not None

    # 手动分组：只派给 A、B；迟到者不在名单内
    assignment = _publish(
        client,
        headers,
        code,
        word_ids,
        student_ids=[str(student_a_row.id), str(student_b_row.id)],
    )

    # A 全对完成；B 只答一题（部分作答不算完成）
    session_a = _start_session(client, student_a["headers"], code)
    _answer(client, student_a["headers"], session_a, 0, "apple")
    _answer(client, student_a["headers"], session_a, 1, "banana")
    session_b = _start_session(client, student_b["headers"], code)
    _answer(client, student_b["headers"], session_b, 0, "aple")

    classroom_row = db.get(Classroom, uuid.UUID(classroom["id"]))
    report = _report(db, classroom_row, granularity="month", periods=2)
    current = report.items[-1]
    # 分母固定为发布名单 A、B；迟到者不入分母
    assert current.assigned_targets == 2
    assert current.completed_targets == 1
    assert current.completion_rate == 50

    # 名单里没有迟到者
    targets = db.exec(
        select(VocabularyAssignmentTarget).where(
            VocabularyAssignmentTarget.assignment_id == uuid.UUID(assignment["id"])
        )
    ).all()
    assert {t.student_id for t in targets} == {student_a_row.id, student_b_row.id}
    assert late is not None


# ── 掌握度分段阈值 ──────────────────────────────────────────────────


def test_trend_bands_match_mastery_thresholds(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "学生甲")
    student_row = student_db_row(db, student["student"]["id"])
    assert student_row is not None

    book = _make_public_book(client, superuser_token_headers, WORDS_4)
    words = book["words"]
    assignment = _publish(client, headers, code, [w["id"] for w in words])
    assignment_id = uuid.UUID(assignment["id"])
    classroom_id = uuid.UUID(classroom["id"])

    # alpha 1/2=50% 低；bravo 3/5=60% 中；charlie 3/3=100% 高；delta 无首答
    item_index = 0
    for n in range(2):
        _seed_answer(
            db,
            classroom_id=classroom_id,
            student_id=student_row.id,
            assignment_id=assignment_id,
            word=words[0],
            days_old=0,
            is_correct=(n == 0),
            item_index=item_index,
        )
        item_index += 1
    for n in range(5):
        _seed_answer(
            db,
            classroom_id=classroom_id,
            student_id=student_row.id,
            assignment_id=assignment_id,
            word=words[1],
            days_old=0,
            is_correct=(n < 3),
            item_index=item_index,
        )
        item_index += 1
    for _ in range(3):
        _seed_answer(
            db,
            classroom_id=classroom_id,
            student_id=student_row.id,
            assignment_id=assignment_id,
            word=words[2],
            days_old=0,
            is_correct=True,
            item_index=item_index,
        )
        item_index += 1

    classroom_row = db.get(Classroom, classroom_id)
    report = _report(db, classroom_row, granularity="month", periods=2)
    current = report.items[-1]
    assert current.low_count == 1
    assert current.mid_count == 1
    assert current.high_count == 1
    assert current.no_data_count == 1


# ── 到期未复习（当前状态回算）───────────────────────────────────────


def test_trend_due_unreviewed_current_state_backcalc(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "学生甲")
    student_row = student_db_row(db, student["student"]["id"])
    assert student_row is not None
    student_user_id = student_row.user_id
    assert student_user_id is not None

    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    words = book["words"]
    _publish(client, headers, code, [w["id"] for w in words])

    past = datetime.now(UTC) - timedelta(days=2)
    future = datetime.now(UTC) + timedelta(days=40)
    db.add(
        VocabularyReviewState(
            user_id=student_user_id,
            word_id=uuid.UUID(words[0]["id"]),
            capability="spelling",
            state="learning",
            due_at=past,
        )
    )
    db.add(
        VocabularyReviewState(
            user_id=student_user_id,
            word_id=uuid.UUID(words[1]["id"]),
            capability="spelling",
            state="review",
            due_at=future,
        )
    )
    db.commit()

    classroom_row = db.get(Classroom, uuid.UUID(classroom["id"]))
    report = _report(db, classroom_row, granularity="month", periods=2)
    # 只有到期（past）条目计入；未来到期不计
    assert report.items[-1].due_unreviewed == 1


# ── CSV ──────────────────────────────────────────────────────────────


def test_trend_csv_export(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    make_student(db, client, code, "学生甲")

    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    _publish(client, headers, code, [w["id"] for w in book["words"]])

    resp = client.get(
        TREND_CSV.format(code=code),
        params={"granularity": "month", "periods": 2},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    raw = resp.content
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0][:4] == ["周期", "period_start", "period_end", "目标数"]
    assert len(rows) == 3  # 表头 + 2 周期
    # 空周期完成率 / 正确率留空，不写 0
    empty_row = rows[1]
    assert empty_row[5] == ""
    assert empty_row[8] == ""


# ── 权限 ────────────────────────────────────────────────────────────


def test_trend_permission_gates(
    client: TestClient,
    db: Session,
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    # 非本班教师 → 403
    _other, other_headers = _login_teacher(db, client)
    assert (
        client.get(
            TREND.format(code=code),
            params={"granularity": "month"},
            headers=other_headers,
        ).status_code
        == 403
    )

    # 不存在的课堂码 → 404
    assert (
        client.get(
            TREND.format(code="NOPE404"),
            params={"granularity": "month"},
            headers=headers,
        ).status_code
        == 404
    )

    # vocabulary 模块关闭 → 趋势为只读历史端点，关闭态仍 200（#567 第 3 项）；
    # 写操作的模块 403 口径由 test_module_readonly_history.py 逐条固定。
    module_rows = list(
        db.exec(
            select(TenantModule).where(
                TenantModule.tenant_id == teacher.tenant_id,  # type: ignore[arg-type]
                TenantModule.module_key == "vocabulary",
            )
        ).all()
    )
    for row in module_rows:
        row.enabled = False
    db.commit()
    try:
        resp = client.get(
            TREND.format(code=code),
            params={"granularity": "month"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
    finally:
        for row in module_rows:
            row.enabled = True
        db.commit()
