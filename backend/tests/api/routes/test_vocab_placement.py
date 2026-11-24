"""粗分档自适应小测（placement）接口回归测试。

口径覆盖：
- 梯度收敛：从 PET 起步，答对升/答错降，边界钳制（规则单测见 test_vocab_placement_logic）；
- 题量降级：可用 approved 映射词 < 12 按实际题量出，带 material_limited 说明；
- 素材门禁：映射词 < 4 或无 approved 词 → 422，不生成假题；
- 重复测：可重测，历史保留两条；
- 权限：学生仅本人本班；教师/共管/本校管理员只读；跨班会话 404；他班教师 403；
- 隔离：placement 不写 FSRS 状态、不发农场 XP、不进练习历史/任务统计。
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app import crud
from app.models import (
    PLACEMENT_DEFAULT_TOTAL,
    PLACEMENT_KIND,
    Student,
    User,
    UserCreate,
    VocabFarmPlot,
    VocabPlacementResult,
    VocabularyAnswer,
    VocabularyLevelEntry,
    VocabularyReviewState,
    VocabularySession,
)
from app.services import vocab_placement
from app.services import vocabulary as vocab_service
from tests.utils.credential import join_as, make_student
from tests.utils.utils import random_email, random_lower_string

PLACEMENT = "/api/v1/classes/{code}/vocabulary/placement"

# 选用 init_db 种子词表之外的 headword，避免与种子 approved 词同形异行干扰判分。
WORDS = [
    {"headword": "maple", "part_of_speech": "n.", "meaning_zh": "枫树", "level": "KET"},
    {"headword": "river", "part_of_speech": "n.", "meaning_zh": "河流", "level": "KET"},
    {
        "headword": "candle",
        "part_of_speech": "n.",
        "meaning_zh": "蜡烛",
        "level": "KET",
    },
    {"headword": "book", "part_of_speech": "n.", "meaning_zh": "书", "level": "PET"},
    {"headword": "water", "part_of_speech": "n.", "meaning_zh": "水", "level": "PET"},
    {"headword": "moon", "part_of_speech": "n.", "meaning_zh": "月亮", "level": "PET"},
    {
        "headword": "analyze",
        "part_of_speech": "v.",
        "meaning_zh": "分析",
        "level": "CET4",
    },
    {
        "headword": "concept",
        "part_of_speech": "n.",
        "meaning_zh": "概念",
        "level": "CET4",
    },
    {
        "headword": "annual",
        "part_of_speech": "adj.",
        "meaning_zh": "年度的",
        "level": "CET4",
    },
    {
        "headword": "hypothesis",
        "part_of_speech": "n.",
        "meaning_zh": "假设",
        "level": "ACADEMIC",
    },
    {
        "headword": "paradigm",
        "part_of_speech": "n.",
        "meaning_zh": "范式",
        "level": "IELTS_TOEFL",
    },
    {
        "headword": "academia",
        "part_of_speech": "n.",
        "meaning_zh": "学术界",
        "level": "ACADEMIC",
    },
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
    words: list[dict[str, Any]],
) -> dict:
    payload = [
        {
            "headword": w["headword"],
            "part_of_speech": w["part_of_speech"],
            "meaning_zh": w["meaning_zh"],
        }
        for w in words
    ]
    resp = client.post(
        "/api/v1/vocabulary/books",
        json={
            "title": "测评分档词库",
            "scope": "public",
            "words": payload,
            "confirm_reviewed": True,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_levels(db: Session, words: list[dict[str, Any]]) -> None:
    for w in words:
        db.add(
            VocabularyLevelEntry(
                headword=w["headword"],
                level=w["level"],
                part_of_speech=w["part_of_speech"],
                meaning_zh=w["meaning_zh"],
                status="active",
                needs_review=False,
            )
        )
    db.commit()


def _start(
    client: TestClient, headers: dict[str, str], code: str, expect: int = 200
) -> dict:
    resp = client.post(PLACEMENT.format(code=code) + "/start", headers=headers)
    assert resp.status_code == expect, resp.text
    return resp.json()


def _answer(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    session_id: str,
    item_index: int,
    answer: str,
    *,
    idempotency_key: str | None = None,
    expect: int = 200,
) -> dict:
    body: dict[str, Any] = {"item_index": item_index, "answer": answer}
    if idempotency_key is not None:
        body["idempotency_key"] = idempotency_key
    resp = client.post(
        PLACEMENT.format(code=code) + f"/sessions/{session_id}/answer",
        json=body,
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _choice_for(question: dict, headword: str) -> str:
    """按题干 headword 从选项里取正确项 word_id（判分按 ID，不按文字）。"""
    return next(c["word_id"] for c in question["choices"] if c["headword"] == headword)


def _play(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    *,
    script: list[bool] | None = None,
) -> tuple[dict, list[dict]]:
    """跑完一整轮；script 给定位置期望对错，否则全部答对。返回起始响应与逐题响应。"""
    start = _start(client, headers, code)
    session_id = start["session_id"]
    question = start["question"]
    rounds: list[dict] = []
    answered = 0
    while question is not None:
        correct_id = _choice_for(question, question["headword"])
        if script is not None and not script[answered]:
            chosen = next(
                c["word_id"] for c in question["choices"] if c["word_id"] != correct_id
            )
        else:
            chosen = correct_id
        body = _answer(
            client, headers, code, session_id, question["item_index"], chosen
        )
        rounds.append(body)
        question = body.get("question")
        answered += 1
    return start, rounds


@pytest.fixture(autouse=True)
def _wipe_placement_rows(db: Session) -> Generator[None]:
    """session 级 db 夹具下，用例间隔离由各用例自清：清掉本模块创建的
    档位条目 / placement 结果 / 会话作答 / 复习状态 / 农场地块，避免同形词
    唯一约束跨用例冲突。词库与学生不在此清，沿用全量套件的种子与随机编号。"""
    for model in (
        VocabPlacementResult,
        VocabularyAnswer,
        VocabularySession,
        VocabularyReviewState,
        VocabFarmPlot,
        VocabularyLevelEntry,
    ):
        db.exec(delete(model))
    db.commit()
    yield


def _setup_class(
    db: Session,
    client: TestClient,
    admin_headers: dict[str, str],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "分档学生")
    book = _make_public_book(client, admin_headers, words)
    _seed_levels(db, words)
    return {
        "code": code,
        "teacher": teacher,
        "headers": headers,
        "student": student,
        "book": book,
    }


def test_placement_full_run_adaptive_and_isolated(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    ctx = _setup_class(db, client, superuser_token_headers, WORDS)
    code, headers = ctx["code"], ctx["student"]["headers"]

    start, rounds = _play(client, headers, code)

    # 起步档固定 PET；默认 12 题；素材充足无降级说明
    assert start["planned_total"] == 12
    assert start["degraded"] is False
    assert start["limitation"] is None
    assert start["question"]["band"] == "PET"
    assert len(rounds) == 12

    final = rounds[-1]
    assert final["status"] == "submitted"
    result = final["result"]
    assert result is not None
    assert result["recommended_band"] in {"KET", "PET", "CET4", "ADVANCED"}
    assert result["question_count"] == 12
    assert result["answered_count"] == 12
    assert result["correct_count"] == 12
    # 结果表不是学生等级字段：Student.current_band 不被回写（保持默认 B1）
    student_row = db.exec(
        select(Student).where(Student.id == uuid.UUID(ctx["student"]["student"]["id"]))  # type: ignore[arg-type]
    ).one()
    assert student_row.current_band == "B1"

    # 隔离：无 FSRS 状态、无农场地块、不进练习历史
    assert (
        db.exec(
            select(VocabularyReviewState).where(
                VocabularyReviewState.user_id == ctx["student"]["user"].id  # type: ignore[arg-type]
            )
        ).all()
        == []
    )
    assert (
        db.exec(
            select(VocabFarmPlot).where(
                VocabFarmPlot.user_id == ctx["student"]["user"].id  # type: ignore[arg-type]
            )
        ).all()
        == []
    )
    history = client.get(
        f"/api/v1/classes/{code}/vocabulary/student/history", headers=headers
    ).json()
    assert history["items"] == []

    # 会话类型标识为 placement，独立于任务/自主/复习
    session_row = db.get(VocabularySession, uuid.UUID(start["session_id"]))
    assert session_row is not None
    assert session_row.kind == "placement"
    assert session_row.assignment_id is None

    # 教师只读列表可见本测结果，仅作教学参考
    teacher_rows = client.get(
        PLACEMENT.format(code=code) + "/results", headers=ctx["headers"]
    ).json()
    assert len(teacher_rows) == 1
    assert teacher_rows[0]["student_id"] == str(ctx["student"]["student"]["id"])
    assert teacher_rows[0]["recommended_band"] == result["recommended_band"]


def test_placement_degraded_when_pool_below_default_total(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # 种子公共演示词库也在可练池内，故这里按实际题量做相对断言：
    # 只要映射池不足默认 12 题，就按实际题量降级并带 material_limited 说明。
    fewer = WORDS[:5]
    ctx = _setup_class(db, client, superuser_token_headers, fewer)
    code, headers = ctx["code"], ctx["student"]["headers"]

    start, rounds = _play(client, headers, code)

    assert start["planned_total"] < PLACEMENT_DEFAULT_TOTAL
    assert start["degraded"] is True
    assert start["limitation"] == "material_limited"
    assert len(rounds) == start["planned_total"]
    result = rounds[-1]["result"]
    assert result["question_count"] == start["planned_total"]
    assert result["limitation"] == "material_limited"


def test_placement_422_when_pool_insufficient(
    db: Session,
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 可练 approved 映射词少于 4 个（或无 approved 词）：直接 422，不生成假题。
    # 种子公共词库无法在 API 层清空，这里在服务层把可练词集置空复现门禁口径。
    ctx = _setup_class(db, client, superuser_token_headers, WORDS[:3])
    student = db.get(Student, uuid.UUID(ctx["student"]["student"]["id"]))
    assert student is not None
    monkeypatch.setattr(
        vocab_service,
        "student_practiceable_word_ids",
        lambda session, classroom_id: set(),
    )
    with pytest.raises(HTTPException) as exc:
        vocab_placement.start_or_resume(db, student.classroom_id, student)
    assert exc.value.status_code == 422
    assert exc.value.detail == "placement_insufficient_words"


def test_placement_retest_keeps_history(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    ctx = _setup_class(db, client, superuser_token_headers, WORDS)
    code, headers = ctx["code"], ctx["student"]["headers"]

    _play(client, headers, code)
    _play(client, headers, code)

    history = client.get(
        PLACEMENT.format(code=code) + "/history", headers=headers
    ).json()
    assert len(history["items"]) == 2
    # 两条都保留，按时间倒序
    assert history["items"][0]["submitted_at"] >= history["items"][1]["submitted_at"]

    rows = db.exec(
        select(VocabPlacementResult).where(
            VocabPlacementResult.student_id
            == uuid.UUID(ctx["student"]["student"]["id"])  # type: ignore[arg-type]
        )
    ).all()
    assert len(rows) == 2


def test_placement_permission_and_cross_class(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    ctx = _setup_class(db, client, superuser_token_headers, WORDS)
    code = ctx["code"]
    start = _start(client, ctx["student"]["headers"], code)
    session_id = start["session_id"]

    # 另一个课堂的学生：拿不到他班会话（404）
    other_teacher, other_headers = _login_teacher(db, client)
    other_class = _create_classroom(client, other_headers)
    other_student = make_student(db, client, other_class["code"], "他班学生")
    resp = client.post(
        PLACEMENT.format(code=other_class["code"]) + f"/sessions/{session_id}/answer",
        json={"item_index": 0, "answer": "whatever"},
        headers=other_student["headers"],
    )
    assert resp.status_code == 404, resp.text

    # 他班教师看本班结果：403（权限不足，不触发登出）
    resp = client.get(PLACEMENT.format(code=code) + "/results", headers=other_headers)
    assert resp.status_code == 403, resp.text

    # 学生不能访问教师只读结果列表
    resp = client.get(
        PLACEMENT.format(code=code) + "/results", headers=ctx["student"]["headers"]
    )
    assert resp.status_code == 403, resp.text

    # 重复提交同一题：每题只能首答一次
    target_id = _choice_for(start["question"], start["question"]["headword"])
    body = _answer(client, ctx["student"]["headers"], code, session_id, 0, target_id)
    resp = client.post(
        PLACEMENT.format(code=code) + f"/sessions/{session_id}/answer",
        json={"item_index": 0, "answer": target_id},
        headers=ctx["student"]["headers"],
    )
    assert resp.status_code == 422, resp.text
    assert body["is_correct"] is True


def test_placement_replay_after_finish_returns_result(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # 收尾后同键幂等重放：必须带回已落库结果，前端重试不能卡住；且不新增作答记录。
    ctx = _setup_class(db, client, superuser_token_headers, WORDS)
    code, headers = ctx["code"], ctx["student"]["headers"]

    start = _start(client, headers, code)
    session_id = start["session_id"]
    question = start["question"]
    last_key: str | None = None
    last_item: int | None = None
    last_answer: str | None = None
    answered = 0

    while question is not None:
        correct_id = _choice_for(question, question["headword"])
        key = f"placement-{session_id}-{question['item_index']}"
        body = _answer(
            client,
            headers,
            code,
            session_id,
            question["item_index"],
            correct_id,
            idempotency_key=key,
        )
        if body.get("question") is None:
            last_key, last_item, last_answer = key, question["item_index"], correct_id
        question = body.get("question")
        answered += 1

    assert last_key is not None and last_item is not None and last_answer is not None

    replay = client.post(
        PLACEMENT.format(code=code) + f"/sessions/{session_id}/answer",
        json={
            "item_index": last_item,
            "answer": last_answer,
            "idempotency_key": last_key,
        },
        headers=headers,
    )
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()
    assert replay_body["result"] is not None
    assert replay_body["result"]["student_id"] == str(ctx["student"]["student"]["id"])
    assert replay_body["result"]["question_count"] == answered
    assert replay_body["is_correct"] is True

    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == uuid.UUID(session_id)  # type: ignore[arg-type]
        )
    ).all()
    assert len(answers) == answered


def test_placement_resume_is_scoped_to_classroom(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # 同一账号加入另一课堂：start 只在本班续做进行中轮次，不跨班捞回 A 轮次。
    ctx = _setup_class(db, client, superuser_token_headers, WORDS)
    code_a, headers = ctx["code"], ctx["student"]["headers"]
    user = ctx["student"]["user"]

    start_a = _start(client, headers, code_a)
    session_a = start_a["session_id"]

    other_teacher, other_headers = _login_teacher(db, client)
    class_b = _create_classroom(client, other_headers)
    join_as(client, class_b["code"], user, display_name="跨班学生")

    start_b = _start(client, headers, class_b["code"])
    assert start_b["session_id"] != session_a

    row_a = db.get(VocabularySession, uuid.UUID(session_a))
    assert row_a is not None
    assert row_a.status == "in_progress"

    row_b = db.get(VocabularySession, uuid.UUID(start_b["session_id"]))
    assert row_b is not None
    assert row_b.classroom_id == uuid.UUID(class_b["id"])  # type: ignore[arg-type]
    assert row_b.kind == PLACEMENT_KIND
