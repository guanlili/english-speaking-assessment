"""FSRS 记忆复习（#517 第二批）API 测试：队列/每日负担/双能力分离/跨班连续/口径隔离。

守的既有契约：
- 首答仍是统计唯一口径：FSRS 状态独立落库，不回填 VocabularyAnswer 与教师统计；
- 错词历史错误次数只增不减，「待复习」状态不折算旧计数；
- 教师任务快照不可变；复习轮不改历史 session 的 snapshot_items；
- 旧 kind=review（错词专项）默认行为不变；新队列 kind=review_fsrs 明确分列；
- 测验（quiz）不接入 FSRS：考试语义与判分口径与学习反馈分离。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.models import (
    VocabularyAnswer,
    VocabularyReviewState,
    VocabularySession,
)
from app.services import vocabulary_review
from tests.api.routes.test_vocabulary_student import (
    STUDENT,
    _create_classroom,
    _login_teacher,
    _make_class_book,
    _make_public_book,
    _start_self,
    _words,
    _wrong_words,
)
from tests.utils.credential import make_student

VOCAB = "/api/v1/vocabulary"


def _queue(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(f"{STUDENT.format(code=code)}/review-queue", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _stats(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(f"{STUDENT.format(code=code)}/review-stats", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_fsrs(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.post(
        f"{STUDENT.format(code=code)}/sessions",
        json={"kind": "review_fsrs"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _answer(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    answer: str,
    prompt_type: str = "meaning",
) -> dict:
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={"item_index": item_index, "prompt_type": prompt_type, "answer": answer},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _finish(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    plan: dict,
    spelling: dict[str, str],
) -> None:
    for item in plan["items"]:
        if not item["answered"]:
            _answer(
                client,
                headers,
                session_id,
                item["item_index"],
                spelling[item["meaning_zh"]],
            )


def _book_words(
    client: TestClient, headers: dict[str, str], code: str, book_id: str
) -> list[dict]:
    resp = client.get(f"{STUDENT.format(code=code)}/books/{book_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["words"]


def _states(db: Session, user_id: uuid.UUID) -> list[VocabularyReviewState]:
    return list(
        db.exec(
            select(VocabularyReviewState).where(
                VocabularyReviewState.user_id == user_id  # type: ignore[arg-type]
            )
        ).all()
    )


# ── 首答写入：练习轮独立首答落 FSRS；错词历史计数不被改写 ──────────────


def test_practice_first_answer_persists_fsrs_state(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_class_book(client, headers, classroom["id"], _words(5, "fs"))
    student = make_student(db, client, classroom["code"])
    spelling = {
        w["meaning_zh"]: w["headword"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    }

    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{created['session_id']}",
        headers=student["headers"],
    ).json()
    wrong_meaning = plan["items"][0]["meaning_zh"]
    wrong_headword = spelling[wrong_meaning]
    for item in plan["items"]:
        headword = spelling[item["meaning_zh"]]
        _answer(
            client,
            student["headers"],
            created["session_id"],
            item["item_index"],
            f"x{headword}" if headword == wrong_headword else headword,
        )

    states = _states(db, student["user"].id)
    assert len(states) == 5
    by_headword: dict[str, VocabularyReviewState] = {}
    words = {
        w["id"]: w["headword"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    }
    for row in states:
        by_headword[words[str(row.word_id)]] = row

    wrong_state = by_headword[wrong_headword]
    assert wrong_state.last_rating == "again"
    assert wrong_state.last_is_correct is False
    assert wrong_state.lapses == 1
    for headword, row in by_headword.items():
        if headword != wrong_headword:
            assert row.last_rating == "good"
            assert row.lapses == 0

    # 错词本历史口径不变：错词只记一条、错误次数 1；FSRS 状态不折算旧计数
    wrong = _wrong_words(client, student["headers"], classroom["code"])
    assert len(wrong) == 1
    assert wrong[0]["headword"] == wrong_headword
    assert wrong[0]["wrong_count"] == 1

    # 自主练习不产生任务进度（当前学生的会话 assignment_id 全空；共享库内其他学生会话不计入）
    task_sessions = db.exec(
        select(VocabularySession).where(
            VocabularySession.student_id == student["user"].id,  # type: ignore[attr-defined]
            col(VocabularySession.assignment_id).is_not(None),
        )
    ).all()
    assert task_sessions == []


# ── 认读 / 拼写状态各自独立，互不影响 ──────────────────────────────────


def test_recognition_and_spelling_states_do_not_interfere(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_class_book(client, headers, classroom["id"], _words(4, "sep"))
    student = make_student(db, client, classroom["code"])
    words = _book_words(client, student["headers"], classroom["code"], book["id"])
    word_by_headword = {w["headword"]: w["id"] for w in words}

    # 第一轮：英译中（认读）全部答对（正确项即本题词条 ID）
    created = _start_self(
        client,
        student["headers"],
        classroom["code"],
        book["id"],
        prompt_types=["en_zh"],
    )
    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{created['session_id']}",
        headers=student["headers"],
    ).json()
    for item in plan["items"]:
        _answer(
            client,
            student["headers"],
            created["session_id"],
            item["item_index"],
            word_by_headword[item["headword"]],
            prompt_type="en_zh",
        )

    recognition = [
        s for s in _states(db, student["user"].id) if s.capability == "recognition"
    ]
    spelling = [
        s for s in _states(db, student["user"].id) if s.capability == "spelling"
    ]
    assert len(recognition) == 4
    assert spelling == []
    assert all(s.reps == 1 and s.lapses == 0 for s in recognition)

    # 第二轮：看义拼写（拼写）全部答对——认读行 reps/lapses 保持不变
    spelling_map = {
        w["meaning_zh"]: w["headword"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    }
    second = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan2 = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{second['session_id']}",
        headers=student["headers"],
    ).json()
    _finish(client, student["headers"], second["session_id"], plan2, spelling_map)

    recognition_after = [
        s for s in _states(db, student["user"].id) if s.capability == "recognition"
    ]
    spelling_after = [
        s for s in _states(db, student["user"].id) if s.capability == "spelling"
    ]
    assert len(recognition_after) == 4
    assert len(spelling_after) == 4
    assert all(s.reps == 1 and s.lapses == 0 for s in recognition_after)
    assert all(s.last_rating == "good" for s in spelling_after)


# ── 队列摘要、每日上限、排序与统计 ──────────────────────────────────────


def _seed_due_states(
    db: Session,
    user_id: uuid.UUID,
    word_ids: list[str],
    *,
    review_today: int = 0,
) -> None:
    now = datetime.now(UTC)
    for word_id in word_ids:
        existing = db.exec(
            select(VocabularyReviewState).where(
                VocabularyReviewState.user_id == user_id,  # type: ignore[arg-type]
                VocabularyReviewState.word_id == uuid.UUID(word_id),  # type: ignore[arg-type]
                VocabularyReviewState.capability == "spelling",  # type: ignore[arg-type]
            )
        ).first()
        if existing is None:
            vocabulary_review.record_first_answer(
                db,
                user_id=user_id,
                word_id=uuid.UUID(word_id),
                prompt_type="meaning",
                is_correct=True,
            )
    rows = db.exec(
        select(VocabularyReviewState).where(VocabularyReviewState.user_id == user_id)  # type: ignore[arg-type]
    ).all()
    for idx, row in enumerate(rows):
        # 全部置为已到期；前 review_today 条记为今日已复习，其余清除复习时间
        row.due_at = now - timedelta(days=idx + 1)
        row.last_review_at = now if idx < review_today else None
    db.commit()


def test_queue_summary_daily_limit_sort_and_stats(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    words = _words(25, "lim")
    book = _make_class_book(client, headers, classroom["id"], words)
    student = make_student(db, client, classroom["code"])
    word_ids = [
        w["id"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    ]
    _seed_due_states(db, student["user"].id, word_ids)

    queue = _queue(client, student["headers"], classroom["code"])
    assert queue["due_today_count"] == 25
    assert queue["reviewed_today_count"] == 0
    assert queue["daily_limit"] == 20
    assert queue["remaining_today_count"] == 20
    assert len(queue["items"]) == 20
    # 逾期天数降序 → 遗忘次数降序；条目带可解释字段
    overdue = [i["overdue_days"] for i in queue["items"]]
    assert overdue == sorted(overdue, reverse=True)
    first = queue["items"][0]
    assert {
        "due_at",
        "interval_days",
        "reps",
        "lapses",
        "last_rating",
        "suggested_prompt_types",
    } <= set(first)
    assert first["suggested_prompt_types"]  # 拼写能力建议输入词形题型

    stats = _stats(client, student["headers"], classroom["code"])
    assert stats["tracked_count"] == 25
    assert stats["due_count"] == 25
    assert stats["reviewed_today_count"] == 0
    assert stats["spelling_count"] == 25

    # 今日已复习 1 条 → 剩余额度 19，条目截断到 19
    _seed_due_states(
        db,
        student["user"].id,
        word_ids,
        review_today=1,
    )
    queue = _queue(client, student["headers"], classroom["code"])
    assert queue["reviewed_today_count"] == 1
    assert queue["remaining_today_count"] == 19
    assert len(queue["items"]) == 19


# ── 跨班连续性：状态按 User 汇总，历史 session 保留原班级 ────────────────


def test_cross_class_state_follows_user_history_keeps_classroom(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _ta, ha = _login_teacher(db, client)
    _tb, hb = _login_teacher(db, client)
    class_a = _create_classroom(client, ha)
    class_b = _create_classroom(client, hb)
    public = _make_public_book(
        client,
        superuser_token_headers,
        _words(3, "cross"),
        f"跨班词库{uuid.uuid4().hex[:6]}",
    )
    student = make_student(db, client, class_a["code"])
    from tests.utils.credential import join_as

    join_as(client, class_b["code"], student["user"], display_name="跨班学生")

    spelling = {
        w["meaning_zh"]: w["headword"]
        for w in _book_words(client, student["headers"], class_a["code"], public["id"])
    }
    created = _start_self(client, student["headers"], class_a["code"], public["id"])
    plan = client.get(
        f"{STUDENT.format(code=class_a['code'])}/sessions/{created['session_id']}",
        headers=student["headers"],
    ).json()
    wrong_meaning = plan["items"][0]["meaning_zh"]
    for item in plan["items"]:
        headword = spelling[item["meaning_zh"]]
        _answer(
            client,
            student["headers"],
            created["session_id"],
            item["item_index"],
            f"x{headword}" if item["meaning_zh"] == wrong_meaning else headword,
        )

    # 把答错词条的状态置为已到期，跨班队列才会把它取出来
    wrong_headword = spelling[wrong_meaning]
    words_a = _book_words(client, student["headers"], class_a["code"], public["id"])
    wrong_word_id = next(w["id"] for w in words_a if w["headword"] == wrong_headword)
    wrong_state = db.exec(
        select(VocabularyReviewState).where(
            VocabularyReviewState.user_id == student["user"].id,  # type: ignore[arg-type]
            VocabularyReviewState.word_id == uuid.UUID(wrong_word_id),  # type: ignore[arg-type]
        )
    ).first()
    assert wrong_state is not None
    wrong_state.due_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    # B 班队列仍能看到同一账号在 A 班种下的到期/错误状态
    queue_b = _queue(client, student["headers"], class_b["code"])
    b_headwords = {i["headword"] for i in queue_b["items"]}
    assert wrong_headword in b_headwords

    # 历史 session 仍挂在原 A 班；状态行按 user_id 汇总、不存班级归属
    session_row = db.get(VocabularySession, uuid.UUID(created["session_id"]))
    assert session_row is not None
    assert str(session_row.classroom_id) == class_a["id"]
    states = _states(db, student["user"].id)
    assert all(s.user_id == student["user"].id for s in states)


# ── 旧 review（错词专项）默认行为不变 ──────────────────────────────────


def test_legacy_review_session_default_behavior_unchanged(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_class_book(client, headers, classroom["id"], _words(4, "leg"))
    student = make_student(db, client, classroom["code"])
    spelling = {
        w["meaning_zh"]: w["headword"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    }

    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{created['session_id']}",
        headers=student["headers"],
    ).json()
    wrong_meaning = plan["items"][0]["meaning_zh"]
    for item in plan["items"]:
        headword = spelling[item["meaning_zh"]]
        _answer(
            client,
            student["headers"],
            created["session_id"],
            item["item_index"],
            f"x{headword}" if item["meaning_zh"] == wrong_meaning else headword,
        )

    before = _wrong_words(client, student["headers"], classroom["code"])
    assert len(before) == 1 and before[0]["wrong_count"] == 1

    # 旧 kind=review 仍是错词专项：题单来自历史错词，不读 FSRS 队列
    resp = client.post(
        f"{STUDENT.format(code=classroom['code'])}/sessions",
        json={"kind": "review"},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    legacy = resp.json()
    assert legacy["kind"] == "review"
    assert legacy["total_count"] == 1
    assert legacy["wrong_word_count"] == 1

    kinds = {s.kind for s in db.exec(select(VocabularySession)).all()}  # type: ignore[attr-defined]
    assert "review" in kinds
    assert "review_fsrs" not in kinds

    after = _wrong_words(client, student["headers"], classroom["code"])
    assert after[0]["wrong_count"] == before[0]["wrong_count"]


# ── 测验不接入 FSRS ─────────────────────────────────────────────────────


def test_quiz_answers_are_not_ingested(client: TestClient, db: Session) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_class_book(client, headers, classroom["id"], _words(4, "quiz"))
    student = make_student(db, client, classroom["code"])
    words = _book_words(client, student["headers"], classroom["code"], book["id"])

    pub = client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
        json={
            "word_ids": [w["id"] for w in words],
            "prompt_types": ["meaning"],
            "mode": "quiz",
            "duration_minutes": 30,
            "pass_line": 60,
        },
        headers=headers,
    )
    assert pub.status_code == 200, pub.text
    assignment_id = pub.json()["id"]

    started = client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/sessions",
        json={"assignment_id": assignment_id},
        headers=student["headers"],
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{session_id}",
        headers=student["headers"],
    ).json()
    spelling = {w["meaning_zh"]: w["headword"] for w in words}
    for item in plan["items"]:
        _answer(
            client,
            student["headers"],
            session_id,
            item["item_index"],
            spelling[item["meaning_zh"]],
        )

    # 测验答卷存在，但 FSRS 状态一条不落库
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == uuid.UUID(session_id)
        )  # type: ignore[attr-defined]
    ).all()
    assert len(answers) == 4
    assert _states(db, student["user"].id) == []


# ── FSRS 复习轮：题单固化、幂等续做、快照不被改写 ────────────────────────


def test_fsrs_review_session_idempotent_snapshot_fixed(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_class_book(client, headers, classroom["id"], _words(3, "fsrs"))
    student = make_student(db, client, classroom["code"])
    word_ids = [
        w["id"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    ]
    _seed_due_states(db, student["user"].id, word_ids)

    first = _start_fsrs(client, student["headers"], classroom["code"])
    assert first["kind"] == "review_fsrs"
    assert first["total_count"] == 3

    # 重复开轮：续做同一轮，不产生第二个进行中会话
    second = _start_fsrs(client, student["headers"], classroom["code"])
    assert second["session_id"] == first["session_id"]

    session_row = db.get(VocabularySession, uuid.UUID(first["session_id"]))
    assert session_row is not None
    assert session_row.snapshot_items is not None
    snapshot_before = [dict(item) for item in session_row.snapshot_items]

    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{first['session_id']}",
        headers=student["headers"],
    ).json()
    queue = _queue(client, student["headers"], classroom["code"])
    # 拼写题未答前不透露 headword；按释义比对题单与队列一致
    queue_meanings = {i["meaning_zh"] for i in queue["items"]}
    plan_meanings = {i["meaning_zh"] for i in plan["items"]}
    assert plan_meanings == queue_meanings

    # 作答后快照题单/题序/内容不变
    spelling = {
        w["meaning_zh"]: w["headword"]
        for w in _book_words(client, student["headers"], classroom["code"], book["id"])
    }
    _answer(
        client,
        student["headers"],
        first["session_id"],
        plan["items"][0]["item_index"],
        spelling[plan["items"][0]["meaning_zh"]],
    )
    db.refresh(session_row)
    assert session_row.snapshot_items is not None
    snapshot_after = [dict(item) for item in session_row.snapshot_items]
    assert snapshot_before == snapshot_after
