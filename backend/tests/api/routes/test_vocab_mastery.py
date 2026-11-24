"""班级掌握度 API 测试：分段聚合、任务/时间窗口径隔离、FSRS 分布与权限。

守的口径：
- 只统计本班教师任务轮（kind=task）首答；自主/复习/分班测不混入；
- 零作答词标 no_data，正确率 null，不画成 0%；
- 掌握度不是考试分数/能力等级；wrong_count 不进本口径；
- 权限：非本班教师 403；跨班/不存在课堂 404；跨班任务 404；非法时间窗 422。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.models import (
    User,
    UserCreate,
    VocabularyAnswer,
    VocabularyReviewState,
    VocabularySession,
)
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
MASTERY = "/api/v1/classes/{code}/vocabulary/mastery"

WORDS_4 = [
    {"headword": "apple", "part_of_speech": "n.", "meaning_zh": "苹果"},
    {"headword": "banana", "part_of_speech": "n.", "meaning_zh": "香蕉"},
    {"headword": "cat", "part_of_speech": "n.", "meaning_zh": "猫"},
    {"headword": "dog", "part_of_speech": "n.", "meaning_zh": "狗"},
]

WORDS_2 = [
    {"headword": "egg", "part_of_speech": "n.", "meaning_zh": "鸡蛋"},
    {"headword": "fish", "part_of_speech": "n.", "meaning_zh": "鱼"},
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
    client: TestClient, admin_headers: dict[str, str], words: list[dict], title: str
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
    client: TestClient, headers: dict[str, str], code: str, word_ids: list[str]
) -> dict:
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments",
        json={"word_ids": word_ids, "prompt_types": ["meaning"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_session(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    assignment_id: str | None = None,
) -> str:
    body: dict[str, object] = {}
    if assignment_id is not None:
        body["assignment_id"] = assignment_id
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions", json=body, headers=headers
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


def _seed_state(
    db: Session,
    *,
    user_id: uuid.UUID,
    word_id: uuid.UUID,
    state: str,
    due_at: datetime,
) -> None:
    """置 FSRS 状态：作答链路可能已自动落库同卡，先查再更新避免唯一索引冲突。"""
    existing = db.exec(
        select(VocabularyReviewState).where(
            VocabularyReviewState.user_id == user_id,  # type: ignore[arg-type]
            VocabularyReviewState.word_id == word_id,  # type: ignore[arg-type]
            VocabularyReviewState.capability == "spelling",  # type: ignore[arg-type]
        )
    ).first()
    if existing is None:
        db.add(
            VocabularyReviewState(
                user_id=user_id,
                word_id=word_id,
                capability="spelling",
                state=state,
                due_at=due_at,
            )
        )
    else:
        existing.state = state
        existing.due_at = due_at
    db.commit()


def _seed_task_answer(
    db: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment_id: uuid.UUID,
    word: dict,
    days_old: int,
    is_correct: bool,
    kind: str = "task",
) -> None:
    """直插一条历史首答（任务轮或自主轮），用于时间窗/口径隔离校验。"""
    now = datetime.now(UTC)
    session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=assignment_id if kind == "task" else None,
        kind=kind,
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
            item_index=0,
            attempt_no=1,
            prompt_type="meaning",
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


def _mastery(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    *,
    assignment_id: str | None = None,
    window_days: int = 30,
) -> dict:
    params: dict[str, object] = {"window_days": window_days}
    if assignment_id is not None:
        params["assignment_id"] = assignment_id
    resp = client.get(
        MASTERY.format(code=code),
        params=params,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_word(report: dict) -> dict[str, dict]:
    return {row["headword"]: row for row in report["words"]}


def test_mastery_assignment_scope_bands_fsrs_and_no_data(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    student_a = make_student(db, client, code, "完成者")
    student_b = make_student(db, client, code, "进行者")
    make_student(db, client, code, "未开始者")

    book = _make_public_book(client, superuser_token_headers, WORDS_4, "掌握度四词")
    words = book["words"]
    word_by_head = {w["headword"]: w for w in words}
    assignment = _publish(client, headers, code, [w["id"] for w in words])

    # A 全对前三个；B 第一题拼错、第二题对；C 未开始
    session_a = _start_session(client, student_a["headers"], code)
    _answer(client, student_a["headers"], session_a, 0, "apple")
    _answer(client, student_a["headers"], session_a, 1, "banana")
    _answer(client, student_a["headers"], session_a, 2, "cat")
    session_b = _start_session(client, student_b["headers"], code)
    _answer(client, student_b["headers"], session_b, 0, "aple")
    _answer(client, student_b["headers"], session_b, 1, "banana")

    future = datetime.now(UTC) + timedelta(days=7)
    past = datetime.now(UTC) - timedelta(days=2)
    # FSRS 分布：显式置位每张自动落库的卡，避免 FSRS 初始状态干扰断言。
    # apple: S1 review 未到期 + S2 learning 已到期；banana: 两人 review 未到期；
    # cat: S1 review 未到期；dog: S2 new 已到期
    _seed_state(
        db,
        user_id=student_a["user"].id,
        word_id=uuid.UUID(word_by_head["apple"]["id"]),
        state="review",
        due_at=future,
    )
    _seed_state(
        db,
        user_id=student_b["user"].id,
        word_id=uuid.UUID(word_by_head["apple"]["id"]),
        state="learning",
        due_at=past,
    )
    _seed_state(
        db,
        user_id=student_a["user"].id,
        word_id=uuid.UUID(word_by_head["banana"]["id"]),
        state="review",
        due_at=future,
    )
    _seed_state(
        db,
        user_id=student_b["user"].id,
        word_id=uuid.UUID(word_by_head["banana"]["id"]),
        state="review",
        due_at=future,
    )
    _seed_state(
        db,
        user_id=student_a["user"].id,
        word_id=uuid.UUID(word_by_head["cat"]["id"]),
        state="review",
        due_at=future,
    )
    _seed_state(
        db,
        user_id=student_b["user"].id,
        word_id=uuid.UUID(word_by_head["dog"]["id"]),
        state="new",
        due_at=past,
    )

    report = _mastery(client, headers, code, assignment_id=assignment["id"])
    assert report["scope"] == "assignment"
    assert report["assignment_id"] == assignment["id"]
    assert report["window_days"] == 30
    # 全班：已答 5，首答正确 4 → 80%（中段）
    assert report["answered_count"] == 5
    assert report["correct_first_count"] == 4
    assert report["accuracy_rate"] == 80
    assert report["low_count"] == 1
    assert report["mid_count"] == 0
    assert report["high_count"] == 2
    assert report["no_data_count"] == 1
    # FSRS 条目分布：new 1 / learning 1 / review 4；到期 2 条
    assert report["fsrs_new"] == 1
    assert report["fsrs_learning"] == 1
    assert report["fsrs_review"] == 4
    assert report["due_count"] == 2

    rows = _by_word(report)
    apple = rows["apple"]
    assert apple["answered_count"] == 2
    assert apple["correct_first_count"] == 1
    assert apple["accuracy_rate"] == 50
    assert apple["band"] == "low"
    assert apple["fsrs_new"] == 0
    assert apple["fsrs_learning"] == 1
    assert apple["fsrs_review"] == 1
    assert apple["due_count"] == 1

    banana = rows["banana"]
    assert banana["band"] == "high"
    assert banana["accuracy_rate"] == 100
    assert banana["fsrs_review"] == 2
    assert banana["due_count"] == 0

    dog = rows["dog"]
    assert dog["answered_count"] == 0
    assert dog["accuracy_rate"] is None
    assert dog["band"] == "no_data"
    assert dog["fsrs_new"] == 1
    assert dog["due_count"] == 1


def test_mastery_window_isolation_and_self_practice_excluded(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "近期学生")
    old_student = make_student(db, client, code, "历史学生")
    self_student = make_student(db, client, code, "自主学生")

    book = _make_public_book(client, superuser_token_headers, WORDS_4, "窗隔离四词")
    words = book["words"]
    cat = next(w for w in words if w["headword"] == "cat")
    assignment = _publish(client, headers, code, [w["id"] for w in words])

    # 近期首答走 API 链路
    session = _start_session(client, student["headers"], code)
    _answer(client, student["headers"], session, 2, "cat")

    # 40 天前的历史任务首答（另一学生直插）：7/30 天窗不计入，90 天窗计入
    _seed_task_answer(
        db,
        classroom_id=uuid.UUID(classroom["id"]),
        student_id=uuid.UUID(old_student["student"]["id"]),
        assignment_id=uuid.UUID(assignment["id"]),
        word=cat,
        days_old=40,
        is_correct=True,
        kind="task",
    )
    # 自主练习轮的首答一律不混入掌握度
    _seed_task_answer(
        db,
        classroom_id=uuid.UUID(classroom["id"]),
        student_id=uuid.UUID(self_student["student"]["id"]),
        assignment_id=uuid.UUID(assignment["id"]),
        word=cat,
        days_old=1,
        is_correct=False,
        kind="self",
    )

    for window, answered, correct, accuracy in [
        (7, 1, 1, 100),
        (30, 1, 1, 100),
        (90, 2, 2, 100),
    ]:
        report = _mastery(
            client, headers, code, assignment_id=assignment["id"], window_days=window
        )
        cat_row = next(row for row in report["words"] if row["headword"] == "cat")
        assert cat_row["answered_count"] == answered, f"window={window}"
        assert cat_row["correct_first_count"] == correct
        assert cat_row["accuracy_rate"] == accuracy


def test_mastery_all_tasks_scope_aggregates_across_assignments(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "跨任务学生")

    book1 = _make_public_book(client, superuser_token_headers, WORDS_4, "跨任务四词")
    assignment1 = _publish(client, headers, code, [w["id"] for w in book1["words"]])
    book2 = _make_public_book(client, superuser_token_headers, WORDS_2, "跨任务两词")
    assignment2 = _publish(client, headers, code, [w["id"] for w in book2["words"]])

    # 任务一：apple 答对；任务二：egg 答对
    session1 = _start_session(client, student["headers"], code, assignment1["id"])
    _answer(client, student["headers"], session1, 0, "apple")
    session2 = _start_session(client, student["headers"], code, assignment2["id"])
    _answer(client, student["headers"], session2, 0, "egg")

    # 单任务口径：互不串词
    only1 = _mastery(client, headers, code, assignment_id=assignment1["id"])
    heads1 = {row["headword"] for row in only1["words"]}
    assert "egg" not in heads1
    only2 = _mastery(client, headers, code, assignment_id=assignment2["id"])
    heads2 = {row["headword"] for row in only2["words"]}
    assert "apple" not in heads2

    # 全部任务口径：两任务词条与首答汇总
    all_tasks = _mastery(client, headers, code)
    assert all_tasks["scope"] == "all_tasks"
    assert all_tasks["answered_count"] == 2
    assert all_tasks["correct_first_count"] == 2
    heads_all = {row["headword"] for row in all_tasks["words"]}
    assert {"apple", "egg"} <= heads_all


def test_mastery_permission_gates(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "权限学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_4, "权限四词")
    assignment = _publish(client, headers, code, [w["id"] for w in book["words"]])

    # 非本班教师 → 403
    _other, other_headers = _login_teacher(db, client)
    assert (
        client.get(MASTERY.format(code=code), headers=other_headers).status_code == 403
    )
    # 学生 → 403
    assert (
        client.get(MASTERY.format(code=code), headers=student["headers"]).status_code
        == 403
    )
    # 不存在的课堂码 → 404
    assert (
        client.get(MASTERY.format(code="NOPE404"), headers=headers).status_code == 404
    )

    # 另一间课堂的任务 → 404（不泄露跨班任务存在性）
    other_classroom = _create_classroom(client, other_headers)
    make_student(db, client, other_classroom["code"], "他班学生")
    other_book = _make_public_book(client, superuser_token_headers, WORDS_2, "他班两词")
    other_assignment = _publish(
        client,
        other_headers,
        other_classroom["code"],
        [w["id"] for w in other_book["words"]],
    )
    resp = client.get(
        MASTERY.format(code=code),
        params={"assignment_id": other_assignment["id"]},
        headers=headers,
    )
    assert resp.status_code == 404

    # 非法时间窗 → 422
    bad = client.get(
        MASTERY.format(code=code),
        params={"assignment_id": assignment["id"], "window_days": 14},
        headers=headers,
    )
    assert bad.status_code == 422


def test_mastery_empty_classroom_report(client: TestClient, db: Session) -> None:
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    report = _mastery(client, headers, classroom["code"])
    assert report["answered_count"] == 0
    assert report["correct_first_count"] == 0
    assert report["accuracy_rate"] is None
    assert report["words"] == []
    assert report["due_count"] == 0
