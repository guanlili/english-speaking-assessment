"""词汇 AI 备课与学情辅助：提示词校验/缓存/限流/降级/可见规则 测试。

红线（自动化全部使用可控模拟响应，monkeypatch vocab_ai._chat）：
- 权限：学生只能分析自己的记录；教师词稿只能进自己的词库；
- 未公布答案保护：测验词讲解 422、单次/整体学情不计入未公布作答；
- 草稿确认后入库：accepted_spellings 不从 AI 草稿接收；不自动发布任务；
- 异常输出：非 JSON/缺字段/超长/虚构薄弱词全部拦截或截断；
- 缓存与失效：指纹一致命中缓存，作答变化后重新生成；限流 429；
- 降级：未配置/模型失败 503，练习与判分不受影响；
- 隐私：提示词不含姓名/学号/邮箱。
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.services import vocab_ai
from tests.api.routes.test_vocabulary_student import (
    _create_classroom,
    _login_teacher,
    _make_class_book,
    _spelling_by_meaning,
    _start_self,
    _words,
)
from tests.api.routes.test_vocabulary_student import (
    _plan as _self_plan,
)
from tests.utils.credential import make_student


def _fake_ai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟“已配置 AI”（CI 无 ARK_API_KEY；模型调用仍由 _chat 模拟）。"""
    monkeypatch.setattr(settings, "ARK_API_KEY", "test-key")


VOCAB = "/api/v1/vocabulary"
AI = "/api/v1/vocabulary/ai"
TODAY = "/api/v1/classes/{code}/vocabulary/today"


@pytest.fixture(autouse=True)
def _reset_ai_rate_buckets():
    vocab_ai._rate_buckets.clear()
    yield
    vocab_ai._rate_buckets.clear()


def _publish_quiz(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    word_ids: list[str],
    **extra: object,
) -> dict:
    body: dict = {
        "word_ids": word_ids,
        "prompt_types": ["meaning"],
        "mode": "quiz",
        "duration_minutes": 30,
        "pass_line": 60,
        **extra,
    }
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_quiz(
    client: TestClient, headers: dict[str, str], code: str, assignment_id: str
) -> str:
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment_id},
        headers=headers,
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


def _submit_quiz(client: TestClient, headers: dict[str, str], session_id: str) -> None:
    resp = client.post(f"{VOCAB}/sessions/{session_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text


# ── 未配置降级 ─────────────────────────────────────────────────────


def test_ai_not_configured_degrades(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置密钥：AI 接口 503，练习/作答/确定性判分完全不受影响。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ARK_API_KEY", None)
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2))

    assert (
        client.post(
            f"{AI}/word-drafts",
            json={"theme": "动物", "count": 3},
            headers=teacher_headers,
        ).status_code
        == 503
    )
    assert (
        client.post(
            f"{AI}/word-explanation",
            params={"code": classroom["code"]},
            json={"headword": "apple", "meaning_zh": "苹果"},
            headers=student["headers"],
        ).status_code
        == 503
    )
    assert (
        client.post(
            f"{AI}/session-insight",
            params={"code": classroom["code"]},
            json={"session_id": str(uuid.uuid4())},
            headers=student["headers"],
        ).status_code
        == 503
    )
    # 确定性判分不受影响：自主轮照常作答
    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _self_plan(
        client, student["headers"], classroom["code"], created["session_id"]
    )
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )
    resp = client.post(
        f"{VOCAB}/sessions/{created['session_id']}/answers",
        json={
            "item_index": plan["items"][0]["item_index"],
            "prompt_type": "meaning",
            "answer": spelling[plan["items"][0]["meaning_zh"]],
        },
        headers=student["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_correct"] is True


# ── 教师词条草稿 ───────────────────────────────────────────────────


def test_word_drafts_generation_and_validation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """草稿生成：JSON 栅栏剥离、缺字段丢弃、去重、数量截断、超长截断。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    _fake_ai_key(monkeypatch)
    huge = "x" * 500
    mock_items = [
        {
            "headword": "resilient",
            "part_of_speech": "adj.",
            "meaning_zh": "有韧性的",
            "meaning_en": "able to recover quickly",
            "example_en": huge,  # 超长 → 截断到 512
        },
        {"headword": "resilient", "meaning_zh": "有韧性的"},  # 重复 → 丢弃
        {"headword": "", "meaning_zh": "空词"},  # 缺拼写 → 丢弃
        {"meaning_zh": "缺拼写"},  # 缺拼写 → 丢弃
        {"headword": "genuine", "part_of_speech": "adj.", "meaning_zh": "真的"},
        "not-a-dict",  # 非对象 → 丢弃
        {"headword": "extra1", "meaning_zh": "多余1"},
    ]
    calls: list[tuple[str, str]] = []

    def fake_chat(system: str, user: str, temperature: float = 0.4) -> str:
        calls.append((system, user))
        return "```json\n" + json.dumps(mock_items, ensure_ascii=False) + "\n```"

    monkeypatch.setattr(vocab_ai, "_chat", fake_chat)

    resp = client.post(
        f"{AI}/word-drafts",
        json={
            "theme": "坚持与成长",
            "level": "KET",
            "count": 3,
            "hint": "贴近校园生活",
        },
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["requested_count"] == 3
    assert data["dropped_count"] == 4  # 重复/缺拼写×2/非对象
    assert len(data["drafts"]) == 3
    assert data["drafts"][0]["headword"] == "resilient"
    assert data["drafts"][1]["headword"] == "genuine"
    assert len(data["drafts"][0]["example_en"]) <= 512
    # 生成时间下发
    assert data["generated_at"]
    # 提示词带主题与级别
    assert any("坚持与成长" in user for _system, user in calls)
    # AI 草稿不带 accepted_spellings 字段
    assert all("accepted_spellings" not in d for d in data["drafts"])


def test_word_drafts_model_failure_degrades(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模型输出非 JSON → 503；练习不受影响（无副作用）。"""

    def bad_chat(system: str, user: str, temperature: float = 0.4) -> str:
        return "抱歉，我无法完成这个任务。"

    monkeypatch.setattr(vocab_ai, "_chat", bad_chat)
    _teacher, teacher_headers = _login_teacher(db, client)
    resp = client.post(
        f"{AI}/word-drafts", json={"theme": "天气", "count": 2}, headers=teacher_headers
    )
    assert resp.status_code == 503
    assert "练习" in resp.json()["detail"] or "不受影响" in resp.json()["detail"]


def test_word_drafts_import_and_visibility(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """确认入库：只能进自己的班级词库；accepted_spellings 不被接收；
    重复跳过；不自动发布任务。"""
    teacher, teacher_headers = _login_teacher(db, client)
    _other, other_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(1, "old"))
    drafts = [
        {
            "headword": "brave",
            "part_of_speech": "adj.",
            "meaning_zh": "勇敢的",
            "meaning_en": "not afraid",
            "example_en": "She is brave.",
            "accepted_spellings": ["braive"],  # 注入不可信字段
        },
        {"headword": "old01", "meaning_zh": "词1"},  # 与词库现有词条重复
    ]
    # 别的教师不能写进他的词库
    resp = client.post(
        f"{AI}/word-drafts/import",
        json={"book_id": book["id"], "drafts": drafts},
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text

    resp = client.post(
        f"{AI}/word-drafts/import",
        json={"book_id": book["id"], "drafts": drafts},
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["added"] == 1
    assert data["skipped"] == 1

    words = client.get(f"{VOCAB}/books/{book['id']}", headers=teacher_headers).json()[
        "words"
    ]
    brave = next(w for w in words if w["headword"] == "brave")
    assert brave["accepted_spellings"] is None  # 变体未被接收

    # 不自动发布任务：该课堂没有任何词汇任务
    tasks = client.get(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
        headers=teacher_headers,
    ).json()
    assert tasks == []


def test_word_drafts_rate_limit(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """限流：同一教师超过阈值 429；另一教师不受影响。"""
    _fake_ai_key(monkeypatch)
    monkeypatch.setattr(
        vocab_ai,
        "_chat",
        lambda system, user, temperature=0.4: json.dumps(
            [{"headword": "limit", "meaning_zh": "限额"}]
        ),
    )
    teacher, teacher_headers = _login_teacher(db, client)
    _other, other_headers = _login_teacher(db, client)
    last = None
    for _ in range(vocab_ai.VOCAB_AI_RATE_LIMIT):
        last = client.post(
            f"{AI}/word-drafts",
            json={"theme": "食物", "count": 1},
            headers=teacher_headers,
        )
        assert last.status_code == 200, last.text
    assert (
        client.post(
            f"{AI}/word-drafts",
            json={"theme": "食物", "count": 1},
            headers=teacher_headers,
        ).status_code
        == 429
    )
    resp = client.post(
        f"{AI}/word-drafts",
        json={"theme": "食物", "count": 1},
        headers=other_headers,
    )
    assert resp.status_code == 200, resp.text


# ── 单词讲解 ───────────────────────────────────────────────────────


def test_word_explanation_cache_and_privacy(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """讲解：缓存命中不再调用模型；超长输出截断；提示词不含学生身份。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"], name="张三")
    prompts: list[str] = []
    call_count = {"n": 0}

    def fake_chat(system: str, user: str, temperature: float = 0.4) -> str:
        call_count["n"] += 1
        prompts.append(user)
        return json.dumps(
            {
                "meanings": ["苹果" + "长" * 300],  # 超长 → 截断
                "common_misspellings": ["appl", "appleee", "", 123],
                "memory_tips": ["联想 a+pple", "每天读三遍"],
                "examples": ["I ate an apple.", "An apple a day."],
            },
            ensure_ascii=False,
        )

    _fake_ai_key(monkeypatch)
    monkeypatch.setattr(vocab_ai, "_chat", fake_chat)
    body = {"headword": "apple", "meaning_zh": "苹果"}
    resp = client.post(
        f"{AI}/word-explanation",
        params={"code": classroom["code"]},
        json=body,
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cached"] is False
    assert len(data["meanings"][0]) <= 120
    assert data["common_misspellings"] == ["appl", "appleee"]  # 空/非串被清
    assert len(data["memory_tips"]) == 2

    # 第二次：缓存命中，模型不再调用
    resp = client.post(
        f"{AI}/word-explanation",
        params={"code": classroom["code"]},
        json=body,
        headers=student["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["cached"] is True
    assert call_count["n"] == 1
    # 提示词最小化：不含姓名/学号/邮箱
    assert all("张三" not in p for p in prompts)
    assert all("guistu" not in p for p in prompts)
    assert all("@" not in p for p in prompts)


# ── 测验可见规则 / 学情 ────────────────────────────────────────────


def test_explanation_blocked_for_unpublished_quiz_word(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未公布答案的测验词：讲解 422；公布后开放。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2, "q"))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, classroom["code"], word_ids)
    session_id = _start_quiz(
        client, student["headers"], classroom["code"], assignment["id"]
    )
    _answer(client, student["headers"], session_id, 0, "wrong")
    _submit_quiz(client, student["headers"], session_id)

    _fake_ai_key(monkeypatch)
    monkeypatch.setattr(
        vocab_ai,
        "_chat",
        lambda system, user, temperature=0.4: json.dumps(
            {
                "meanings": ["词义"],
                "common_misspellings": [],
                "memory_tips": [],
                "examples": [],
            }
        ),
    )
    body = {"headword": "q01", "meaning_zh": "词1"}
    blocked = client.post(
        f"{AI}/word-explanation",
        params={"code": classroom["code"]},
        json=body,
        headers=student["headers"],
    )
    assert blocked.status_code == 422, blocked.text

    # 公布答案后开放
    client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments/{assignment['id']}/publish-answers",
        headers=teacher_headers,
    )
    ok = client.post(
        f"{AI}/word-explanation",
        params={"code": classroom["code"]},
        json=body,
        headers=student["headers"],
    )
    assert ok.status_code == 200, ok.text


def test_session_insight_evidence_and_fingerprint(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单次学情：只用本轮真实作答；虚构薄弱词被丢弃；作答变化后重新生成。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(3, "s"))
    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _self_plan(
        client, student["headers"], classroom["code"], created["session_id"]
    )
    by_meaning = {i["meaning_zh"]: i["item_index"] for i in plan["items"]}
    # 词1 答错（真实证据）；其余答对
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词1"],
        "sxx1",
    )
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词2"],
        "s02",
    )
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词3"],
        "s03",
    )

    def fake_chat(system: str, user: str, temperature: float = 0.4) -> str:
        # 虚构词 fake-word 必须被丢弃；s01 是真实错词
        assert "fake-word" not in "s01"  # 自检
        return json.dumps(
            {
                "summary": "本轮答错 1 题，集中在词1。",
                "weak_words": ["s01", "fake-word"],
                "suggestions": ["抄写 s01 三遍并造句"],
            },
            ensure_ascii=False,
        )

    _fake_ai_key(monkeypatch)
    monkeypatch.setattr(vocab_ai, "_chat", fake_chat)
    resp = client.post(
        f"{AI}/session-insight",
        params={"code": classroom["code"]},
        json={"session_id": created["session_id"]},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cached"] is False
    assert data["scope"]["answered_count"] == 3
    assert data["scope"]["total_count"] == 3
    # 虚构词被丢弃，保留真实证据（含你的输入与正确拼写）
    assert [w["headword"] for w in data["weak_words"]] == ["s01"]
    assert data["weak_words"][0]["your_answer"] == "sxx1"
    assert data["weak_words"][0]["correct_spelling"] == "s01"

    # 第二次：指纹一致 → 缓存命中
    resp = client.post(
        f"{AI}/session-insight",
        params={"code": classroom["code"]},
        json={"session_id": created["session_id"]},
        headers=student["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["cached"] is True

    # 作答变化（重试产生新 attempt）→ 指纹变化 → stale/重新生成
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词1"],
        "s01",
    )
    resp = client.post(
        f"{AI}/session-insight",
        params={"code": classroom["code"]},
        json={"session_id": created["session_id"]},
        headers=student["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["cached"] is False  # 重新生成


def test_session_insight_permission_and_quiz_guard(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """他人会话 404；测验未公布答案不提供学情，公布后可生成。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    other = make_student(db, client, classroom["code"], name="同学")
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2, "i"))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, classroom["code"], word_ids)
    session_id = _start_quiz(
        client, student["headers"], classroom["code"], assignment["id"]
    )
    _answer(client, student["headers"], session_id, 0, "wrong")
    _submit_quiz(client, student["headers"], session_id)

    _fake_ai_key(monkeypatch)
    monkeypatch.setattr(
        vocab_ai,
        "_chat",
        lambda system, user, temperature=0.4: json.dumps(
            {"summary": "s", "weak_words": [], "suggestions": []}
        ),
    )
    # 他人访问 → 404
    resp = client.post(
        f"{AI}/session-insight",
        params={"code": classroom["code"]},
        json={"session_id": session_id},
        headers=other["headers"],
    )
    assert resp.status_code == 404, resp.text
    # 未公布 → 422
    resp = client.post(
        f"{AI}/session-insight",
        params={"code": classroom["code"]},
        json={"session_id": session_id},
        headers=student["headers"],
    )
    assert resp.status_code == 422, resp.text
    # 公布答案后可生成
    client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments/{assignment['id']}/publish-answers",
        headers=teacher_headers,
    )
    resp = client.post(
        f"{AI}/session-insight",
        params={"code": classroom["code"]},
        json={"session_id": session_id},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    # 学情证据不泄露未答词的拼写（未答只计数的口径由 scope 承载）


def test_overall_insight_scope_and_publish_guard(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整体学情：明确范围（最近轮×天数）；未公布测验作答不计入。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(4, "o"))
    # 自主轮：错 o01
    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _self_plan(
        client, student["headers"], classroom["code"], created["session_id"]
    )
    by_meaning = {i["meaning_zh"]: i["item_index"] for i in plan["items"]}
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词1"],
        "oxx1",
    )
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词2"],
        "o02",
    )
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词3"],
        "o03",
    )
    _answer(
        client,
        student["headers"],
        created["session_id"],
        by_meaning["词4"],
        "o04",
    )

    captured: dict[str, str] = {}

    def fake_chat(system: str, user: str, temperature: float = 0.4) -> str:
        captured["user"] = user
        return json.dumps(
            {
                "summary": "近期练习里 o01 反复出错。",
                "weak_words": ["o01"],
                "suggestions": ["先复习 o01 的拼写规则"],
            },
            ensure_ascii=False,
        )

    _fake_ai_key(monkeypatch)
    monkeypatch.setattr(vocab_ai, "_chat", fake_chat)
    resp = client.post(
        f"{AI}/overall-insight",
        params={"code": classroom["code"]},
        json={"limit": 10, "days": 30},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scope"]["rounds"] == 1
    assert data["scope"]["days"] == 30
    assert data["scope"]["answered_count"] == 4
    assert [w["headword"] for w in data["weak_words"]] == ["o01"]
    assert data["weak_words"][0]["your_answer"] == "oxx1"
    assert data["generated_at"]
    # 提示词不含身份信息
    assert student["student"]["display_name"] not in captured["user"]

    # 空范围（无任何记录的同学）→ 422
    other = make_student(db, client, classroom["code"], name="无记录同学")
    resp = client.post(
        f"{AI}/overall-insight",
        params={"code": classroom["code"]},
        json={"limit": 10, "days": 30},
        headers=other["headers"],
    )
    assert resp.status_code == 422, resp.text

    # 未公布测验作答不计入：发布测验并答错 quiz-外的词、不公布 →
    # 证据池仍只有 o01（quiz 词不出现）
    quiz_book = _make_class_book(
        client, teacher_headers, classroom["id"], _words(2, "k"), "测验专用"
    )
    quiz_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{quiz_book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, classroom["code"], quiz_ids)
    quiz_session = _start_quiz(
        client, student["headers"], classroom["code"], assignment["id"]
    )
    _answer(client, student["headers"], quiz_session, 0, "kxx1")
    _submit_quiz(client, student["headers"], quiz_session)
    captured.clear()
    resp = client.post(
        f"{AI}/overall-insight",
        params={"code": classroom["code"]},
        json={"limit": 10, "days": 30, "force": True},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert "k01" not in captured["user"]
    # 公布后计入
    client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments/{assignment['id']}/publish-answers",
        headers=teacher_headers,
    )
    captured.clear()
    resp = client.post(
        f"{AI}/overall-insight",
        params={"code": classroom["code"]},
        json={"limit": 10, "days": 30, "force": True},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert "k01" in captured["user"]
