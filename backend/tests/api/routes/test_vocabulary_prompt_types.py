"""四类玩法（英译中/中译英/语境填空/词根拼装）+ 手动分组 + 学习推荐。

第一批验收面（issue #517 V2）：
- 内容不足即拒绝发布（例句/词法/干扰项），不静默出空题；
- 四类题真实判分：选择题按词条 ID，填空/拼装按拼写；
- 题面泄露边界：英译中给英文题干藏释义、中译英给中文题干藏拼写、
  填空与拼装答后才揭示；
- 手动分组派发只发给名单内学生，跨班 ID 一律 422；
- 教师结果按题型拆正确率；学生推荐是规则可解释，不输出等级。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.credential import make_student

API = "/api/v1"
VOCAB = f"{API}/vocabulary"

# 演示用自编词料（不含版权词表内容；教学准确性由学校老师审）
DEMO_WORDS = [
    {
        "headword": "apple",
        "part_of_speech": "n.",
        "meaning_zh": "苹果",
        "example_en": "I ate an apple after lunch.",
    },
    {
        "headword": "banana",
        "part_of_speech": "n.",
        "meaning_zh": "香蕉",
        "example_en": "The banana is still green.",
    },
    {
        "headword": "teacher",
        "part_of_speech": "n.",
        "meaning_zh": "老师",
        "morphology": [
            {"text": "teach", "gloss": "教", "kind": "root"},
            {"text": "er", "gloss": "表人", "kind": "suffix"},
        ],
    },
    {
        "headword": "preheat",
        "part_of_speech": "v.",
        "meaning_zh": "预热",
        "morphology": [
            {"text": "pre", "gloss": "预先", "kind": "prefix"},
            {"text": "heat", "gloss": "加热", "kind": "root"},
        ],
    },
    {
        "headword": "unhappy",
        "part_of_speech": "adj.",
        "meaning_zh": "不开心的",
        "morphology": [
            {"text": "un", "gloss": "不", "kind": "prefix"},
            {"text": "happy", "gloss": "开心", "kind": "root"},
        ],
    },
    {
        "headword": "careless",
        "part_of_speech": "adj.",
        "meaning_zh": "粗心的",
        "example_en": "His careless mistake cost the team a point.",
    },
]

ALL_NEW_TYPES = ["en_zh", "zh_en", "cloze", "roots"]


def _teacher(db: Session, client: TestClient) -> dict[str, str]:
    from app import crud
    from app.models import UserCreate
    from tests.utils.utils import random_email, random_lower_string

    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    resp = client.post(
        f"{API}/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post(f"{API}/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _book(
    client: TestClient,
    headers: dict[str, str],
    words: list[dict],
    classroom_id: str,
) -> dict:
    """建本班词库（班级词库才能被本班教师发布）。"""
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": f"演示词库-{uuid.uuid4().hex[:6]}",
            "scope": "classroom",
            "classroom_id": classroom_id,
            "words": words,
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
    prompt_types: list[str],
    **extra: object,
) -> dict:
    body: dict = {"word_ids": word_ids, "prompt_types": prompt_types}
    body.update(extra)
    resp = client.post(
        f"{API}/classes/{code}/vocabulary/assignments", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _book_words(client: TestClient, headers: dict[str, str], book_id: str) -> list:
    resp = client.get(f"{VOCAB}/books/{book_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["words"]


def _today(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(f"{API}/classes/{code}/vocabulary/today", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _session(
    client: TestClient, headers: dict[str, str], code: str, **body: str
) -> str:
    resp = client.post(
        f"{API}/classes/{code}/vocabulary/sessions", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def _answer(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    prompt_type: str,
    answer: str,
) -> dict:
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": item_index,
            "prompt_type": prompt_type,
            "answer": answer,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _setup(
    client: TestClient, db: Session, words: list[dict]
) -> tuple[dict[str, str], str, dict, list]:
    headers = _teacher(db, client)
    classroom = _classroom(client, headers)
    code = classroom["code"]
    book = _book(client, headers, words, classroom["id"])
    return headers, code, book, _book_words(client, headers, book["id"])


# ── 内容门槛 ───────────────────────────────────────────────────────


def test_book_words_expose_morphology_to_teacher_panel(
    client: TestClient, db: Session
) -> None:
    """教师读词库必须返回 morphology，否则前端恒判 roots「0 词可出」并禁用。

    回归背景：attach_word_levels 在构造 VocabularyWordPublic 时漏传该字段，
    只影响教师 readBook 读路径；DB、发布快照、学生 today 接口均正常。
    """
    _headers, _code, _book_row, words = _setup(client, db, DEMO_WORDS)
    by_headword = {word["headword"]: word for word in words}
    teacher = by_headword["teacher"]
    assert teacher["morphology"] == [
        {"text": "teach", "gloss": "教", "kind": "root"},
        {"text": "er", "gloss": "表人", "kind": "suffix"},
    ]
    assert by_headword["apple"]["morphology"] is None


def test_publish_rejects_types_without_content(client: TestClient, db: Session) -> None:
    """没有例句不能出语境填空；没有词法不能出词根拼装；不足四词不能四选一。"""
    headers, code, _book_row, _words = _setup(client, db, DEMO_WORDS)

    # 语境填空：所选词条全都没有例句
    no_example = _book(
        client,
        headers,
        [
            {"headword": "silent", "part_of_speech": "adj.", "meaning_zh": "安静的"},
            {"headword": "plain", "part_of_speech": "adj.", "meaning_zh": "朴素的"},
            *DEMO_WORDS[2:4],
        ],
        _classroom(client, headers)["id"],
    )
    bad = client.post(
        f"{API}/classes/{code}/vocabulary/assignments",
        json={
            "word_ids": [
                word["id"] for word in _book_words(client, headers, no_example["id"])
            ],
            "prompt_types": ["cloze"],
        },
        headers=headers,
    )
    assert bad.status_code == 422
    assert "语境填空" in bad.json()["detail"]

    # 词根拼装：所选词条全都没有词法拆解
    no_morph = _book(
        client,
        headers,
        [
            DEMO_WORDS[0],
            DEMO_WORDS[1],
            DEMO_WORDS[5],
            {"headword": "garden", "part_of_speech": "n.", "meaning_zh": "花园"},
        ],
        _classroom(client, headers)["id"],
    )
    bad2 = client.post(
        f"{API}/classes/{code}/vocabulary/assignments",
        json={
            "word_ids": [
                word["id"] for word in _book_words(client, headers, no_morph["id"])
            ],
            "prompt_types": ["roots"],
        },
        headers=headers,
    )
    assert bad2.status_code == 422
    assert "词根拼装" in bad2.json()["detail"]

    # 四选一：词条不足四个，生成不了 3 个干扰项
    small = _book(
        client,
        headers,
        [_book_words(client, headers, _book_row["id"])[0], DEMO_WORDS[1]],
        _classroom(client, headers)["id"],
    )
    bad3 = client.post(
        f"{API}/classes/{code}/vocabulary/assignments",
        json={
            "word_ids": [
                word["id"] for word in _book_words(client, headers, small["id"])
            ],
            "prompt_types": ["en_zh"],
        },
        headers=headers,
    )
    assert bad3.status_code == 422
    assert "干扰项" in bad3.json()["detail"]


# ── 题型轮转的覆盖率 ───────────────────────────────────────────────


def test_plan_prompt_types_covers_every_selected_mode() -> None:
    """轮转不能碰巧跳过某种题型：教师勾了四种，题单里四种都要出现。

    这是曾经真实失败过的词序（前两个词只能出词根，随后被选择题/填空
    占位，轮转一旦跳过后面的词就再也轮不到词根）。
    """
    from types import SimpleNamespace

    from app.services.vocabulary_prompt_types import plan_item_prompt_types

    def word(headword: str, example: bool, morph: bool) -> SimpleNamespace:
        return SimpleNamespace(
            headword=headword,
            example_en=f"They used the {headword} yesterday." if example else None,
            morphology=(
                [
                    {"text": headword[:4], "gloss": "词块", "kind": "root"},
                    {"text": headword[4:] or "s", "gloss": "词块", "kind": "suffix"},
                ]
                if morph and len(headword) >= 4
                else None
            ),
        )

    # teacher/preheat 有词法；apple/banana/careless 有例句；unhappy 有词法
    words = [
        word("teach", False, True),
        word("prehe", False, True),
        word("apple", True, False),
        word("banana", True, False),
        word("unhappy", False, True),
        word("careless", True, False),
    ]
    plan = plan_item_prompt_types(words, ["en_zh", "zh_en", "cloze", "roots"])
    types = {item[0] for item in plan}
    assert types == {"en_zh", "zh_en", "cloze", "roots"}


# ── 四类玩法闭环 ───────────────────────────────────────────────────


def test_four_prompt_types_run_end_to_end(client: TestClient, db: Session) -> None:
    """发布→学生看到四种题面→首答→揭示→按揭示答对→结果按题型统计。"""
    headers, code, _book_row, words = _setup(client, db, DEMO_WORDS)
    student = make_student(db, client, code, "四类学生")
    assignment = _publish(
        client,
        headers,
        code,
        [word["id"] for word in words],
        ALL_NEW_TYPES,
    )

    plan = _today(client, student["headers"], code)
    items = plan["items"]
    assert len(items) == len(words)
    types = {item["prompt_type"] for item in items}
    assert types == set(ALL_NEW_TYPES)

    # 题面边界（答题前）
    for item in items:
        prompt_type = item["prompt_type"]
        expected_choices = 4 if prompt_type in ("en_zh", "zh_en") else 0
        assert len(item["choices"]) == expected_choices
        if prompt_type == "en_zh":
            assert item["headword"]
            assert item["meaning_zh"] == ""
        elif prompt_type == "zh_en":
            assert item["headword"] is None
            assert item["meaning_zh"]
            assert all(choice["is_answer"] is False for choice in item["choices"])
        elif prompt_type == "cloze":
            assert item["headword"] is None
            assert "____" in (item["cloze_sentence"] or "")
        elif prompt_type == "roots":
            assert item["headword"] is None
            assert len(item["morph_segments"]) >= 2
            assert all(segment["text"] for segment in item["morph_segments"])

    # 首答：选择题点第一个选项，拼写题乱填；判定必须真实返回
    session_id = _session(client, student["headers"], code)
    first_results: dict[str, list[bool]] = {}
    for item in items:
        prompt_type = item["prompt_type"]
        if prompt_type in ("en_zh", "zh_en"):
            answer = item["choices"][0]["word_id"]
        else:
            answer = "zzz-not-a-word"
        result = _answer(
            client,
            student["headers"],
            session_id,
            item["item_index"],
            prompt_type,
            answer,
        )
        first_results.setdefault(prompt_type, []).append(bool(result["is_correct"]))
        if prompt_type in ("cloze", "roots"):
            assert result["is_correct"] is False, result

    # 已答揭示：题干词形与释义回来，选择题正确项被标记
    revealed = _today(client, student["headers"], code)["items"]
    for item in revealed:
        assert item["answered"] is True
        assert item["headword"]
        if item["prompt_type"] in ("en_zh", "zh_en"):
            assert item["meaning_zh"]
            marks = [
                choice["is_answer"] for choice in item["choices"] if choice["is_answer"]
            ]
            assert len(marks) == 1
        if item["prompt_type"] == "cloze":
            assert "____" in (item["cloze_sentence"] or "")

    # 按揭示内容作答：选择题按正确词条 ID、拼写题按词形（大小写/空白容错）
    second_session = _session(client, student["headers"], code, **{"round": "new"})
    for item in revealed:
        prompt_type = item["prompt_type"]
        if prompt_type in ("en_zh", "zh_en"):
            answer = next(
                choice["word_id"] for choice in item["choices"] if choice["is_answer"]
            )
        else:
            answer = f"  {item['headword'].upper()} "
        result = _answer(
            client,
            student["headers"],
            second_session,
            item["item_index"],
            prompt_type,
            answer,
        )
        assert result["is_correct"] is True, (prompt_type, result)

    # 教师结果：按题型拆首答正确率；重试不改变首答统计
    resp = client.get(
        f"{API}/classes/{code}/vocabulary/results",
        params={"assignment_id": assignment["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    stats = {row["prompt_type"]: row for row in resp.json()["prompt_type_stats"]}
    assert set(stats) == set(ALL_NEW_TYPES)
    for prompt_type, results in first_results.items():
        assert stats[prompt_type]["answered_count"] == len(results)
        assert stats[prompt_type]["correct_first_count"] == sum(results)


def test_self_practice_accepts_new_prompt_types(
    client: TestClient, db: Session
) -> None:
    """自主练习同样能出四类题（不只教师任务里能练）。"""
    headers, code, book, words = _setup(client, db, DEMO_WORDS)
    student = make_student(db, client, code, "自主学生")
    resp = client.post(
        f"{API}/classes/{code}/vocabulary/student/sessions",
        json={
            "kind": "self",
            "book_id": book["id"],
            "word_count": 6,
            "prompt_types": ALL_NEW_TYPES,
        },
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    detail = client.get(
        f"{API}/classes/{code}/vocabulary/student/sessions/{resp.json()['session_id']}",
        headers=student["headers"],
    )
    assert detail.status_code == 200, detail.text
    types = {item["prompt_type"] for item in detail.json()["items"]}
    assert types == set(ALL_NEW_TYPES)


# ── 手动分组派发 ───────────────────────────────────────────────────


def test_manual_group_dispatch(client: TestClient, db: Session) -> None:
    """只发给名单内指定学生；跨班 ID 422；未派发学生看不到任务。"""
    headers, code, _book_row, words = _setup(client, db, DEMO_WORDS)
    student_a = make_student(db, client, code, "组内学生")
    student_b = make_student(db, client, code, "组外学生")

    other = _teacher(db, client)
    other_class = _classroom(client, other)
    outsider = make_student(db, client, other_class["code"], "外班学生")

    assignment = _publish(
        client,
        headers,
        code,
        [word["id"] for word in words],
        ["en_zh", "zh_en"],
        student_ids=[student_a["student"]["id"]],
    )

    rows_a = {
        row["assignment_id"]: row
        for row in _today(client, student_a["headers"], code)["assignments"]
    }
    assert assignment["id"] in rows_a
    rows_b = _today(client, student_b["headers"], code)["assignments"]
    assert assignment["id"] not in {row["assignment_id"] for row in rows_b}

    result = client.get(
        f"{API}/classes/{code}/vocabulary/results",
        params={"assignment_id": assignment["id"]},
        headers=headers,
    )
    assert result.status_code == 200, result.text
    assert result.json()["target_count"] == 1

    bad = client.post(
        f"{API}/classes/{code}/vocabulary/assignments",
        json={
            "word_ids": [word["id"] for word in words],
            "prompt_types": ["meaning"],
            "student_ids": [outsider["student"]["id"]],
        },
        headers=headers,
    )
    assert bad.status_code == 422
    assert "不在本课堂名单" in bad.json()["detail"]


# ── 基础学习推荐 ───────────────────────────────────────────────────


def test_recommendation_is_rule_based(client: TestClient, db: Session) -> None:
    """无历史给起步建议；答错后推荐错词、降题型；输出可解释不含等级。"""
    headers, code, book, words = _setup(client, db, DEMO_WORDS)
    student = make_student(db, client, code, "推荐学生")

    fresh = client.get(
        f"{API}/classes/{code}/vocabulary/student/recommendation",
        headers=student["headers"],
    )
    assert fresh.status_code == 200, fresh.text
    payload = fresh.json()
    assert payload["basis"] == ["no_history"]
    assert payload["accuracy"] is None
    assert payload["suggested_prompt_types"] == ["meaning", "en_zh"]
    assert payload["note_code"] == "rule_based_not_certification"

    _publish(client, headers, code, [word["id"] for word in words], ["meaning"])
    session_id = _session(client, student["headers"], code)
    plan = _today(client, student["headers"], code)
    # 第一题故意答错，其余不答
    item_index = plan["items"][0]["item_index"]
    _answer(client, student["headers"], session_id, item_index, "meaning", "zzz")

    after = client.get(
        f"{API}/classes/{code}/vocabulary/student/recommendation",
        headers=student["headers"],
    )
    assert after.status_code == 200, after.text
    data = after.json()
    assert data["answered_total"] == 1
    assert "low_accuracy" in data["basis"]
    assert "wrong_focus" in data["basis"]
    assert data["suggested_prompt_types"] == ["meaning", "cloze"]
    assert data["suggested_word_count"] == 10
    assert data["focus_words"][0]["wrong_count"] >= 1
    assert all(focus["practiceable"] for focus in data["focus_words"])
