"""学生自主练习与错词学习报告：浏览/开轮/混错词/复习/历史闭环测试。

口径（需求批次 2026-10-06）：
- 浏览授权：active 公共词库 + active 本班词库；他班/归档词库不可见（403）；
- 自主开轮：默认 20 词、不足按实际数量；题单与题序创建后固化（刷新稳定）；
- 与教师任务独立：练过相同词库不产生任务进度，不改任务成绩；
- 混入错词：只取所选词库内的历史错词、最近错误优先、按词条 ID 去重
  （同形异义是独立词条，天然保留）；不足以其他词补足；
- 错词本：历史错误次数只增不减，最近独立首答与最近答对分列；
  复习限定当前可练词库（归档词库的错词不能再练）；
- 报告口径：首答正确率分母为已答题数（接口只下发计数，不预画百分比），
  完成进度分母为本轮总题数；起止时间如实下发。

题单题序是创建时打乱的，测试统一用「词库浏览接口的释义→拼写」映射作答。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import User, UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
TODAY = "/api/v1/classes/{code}/vocabulary/today"
WRONG = "/api/v1/classes/{code}/vocabulary/wrong-words"
STUDENT = "/api/v1/classes/{code}/vocabulary/student"


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


def _make_class_book(
    client: TestClient,
    headers: dict[str, str],
    classroom_id: str,
    words: list[dict],
    title: str = "班级自建词库",
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": title,
            "scope": "classroom",
            "classroom_id": classroom_id,
            "words": words,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_public_book(
    client: TestClient, admin_headers: dict[str, str], words: list[dict], title: str
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={"title": title, "scope": "public", "words": words},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _words(n: int, prefix: str = "w") -> list[dict]:
    return [
        {"headword": f"{prefix}{i:02d}", "part_of_speech": "n.", "meaning_zh": f"词{i}"}
        for i in range(1, n + 1)
    ]


def _spelling_by_meaning(
    client: TestClient, headers: dict[str, str], code: str, book_id: str
) -> dict[str, str]:
    """词库浏览口径：释义 → 拼写（题单题序打乱，测试按释义反查作答）。"""
    resp = client.get(f"{STUDENT.format(code=code)}/books/{book_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return {w["meaning_zh"]: w["headword"] for w in resp.json()["words"]}


def _start_self(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    book_id: str,
    **extra: object,
) -> dict:
    body: dict = {"kind": "self", "book_id": book_id, **extra}
    resp = client.post(
        f"{STUDENT.format(code=code)}/sessions", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_review(
    client: TestClient, headers: dict[str, str], code: str, **extra: object
) -> dict:
    body: dict = {"kind": "review", **extra}
    resp = client.post(
        f"{STUDENT.format(code=code)}/sessions", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plan(
    client: TestClient, headers: dict[str, str], code: str, session_id: str
) -> dict:
    resp = client.get(
        f"{STUDENT.format(code=code)}/sessions/{session_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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


def _finish_round(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    plan: dict,
    spelling: dict[str, str],
) -> None:
    """把未答题目按正确拼写答完（结束本轮）。"""
    for item in plan["items"]:
        if not item["answered"]:
            _answer(
                client,
                headers,
                session_id,
                item["item_index"],
                spelling[item["meaning_zh"]],
            )


def _wrong_words(client: TestClient, headers: dict[str, str], code: str) -> list[dict]:
    resp = client.get(WRONG.format(code=code), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _history(client: TestClient, headers: dict[str, str], code: str) -> list[dict]:
    resp = client.get(f"{STUDENT.format(code=code)}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _seed_wrong_words(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    book_id: str,
    wrong_headwords: list[str],
) -> None:
    """开一轮自主练习：指定单词首答拼错、其余答对（一轮一个错词批次）。"""
    spelling = _spelling_by_meaning(client, headers, code, book_id)
    created = _start_self(client, headers, code, book_id, word_count=10)
    plan = _plan(client, headers, code, created["session_id"])
    for item in plan["items"]:
        headword = spelling[item["meaning_zh"]]
        wrong = headword in wrong_headwords
        _answer(
            client,
            headers,
            created["session_id"],
            item["item_index"],
            f"x{headword}" if wrong else headword,
        )
        if wrong:
            wrong_headwords.remove(headword)


# ── 词库浏览与搜索（权限） ─────────────────────────────────────────


def test_create_book_words_have_stable_position_order(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """建库带词：position 连续赋值，词序按导入顺序稳定。

    曾漏传 position 全默认 0 → ORDER BY position 全平局 → Postgres 返回
    顺序不定（教师预览词序 ≠ 学生测验词序；CI 与本地实测顺序不同，
    vocab quiz 两测例在 CI 确定性翻车即此因）。
    """
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(4, "pos"))
    words = client.get(f"{VOCAB}/books/{book['id']}", headers=teacher_headers).json()[
        "words"
    ]
    assert [w["headword"] for w in words] == [
        "pos01",
        "pos02",
        "pos03",
        "pos04",
    ]
    from sqlmodel import col
    from sqlmodel import select as sm_select

    from app.models import VocabularyBookItem

    positions = db.exec(
        sm_select(VocabularyBookItem.position).where(
            col(VocabularyBookItem.book_id) == uuid.UUID(book["id"])  # type: ignore[arg-type]
        )
    ).all()
    assert sorted(positions) == [1, 2, 3, 4]


def test_student_book_browse_scope_and_search(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """学生浏览 = 公共词库 + 本班词库；他班不可见、归档不可见、可按名称搜索。"""
    teacher, teacher_headers = _login_teacher(db, client)
    _other_teacher, other_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    other_classroom = _create_classroom(client, other_headers)
    student = make_student(db, client, classroom["code"])

    # 唯一标题（测试库跨文件共享，避免与他例词库撞搜索词）
    public_title = f"公共分级词库{uuid.uuid4().hex[:8]}"
    _make_public_book(client, superuser_token_headers, _words(3, "pub"), public_title)
    mine = _make_class_book(client, teacher_headers, classroom["id"], _words(4, "mine"))
    _make_class_book(
        client, other_headers, other_classroom["id"], _words(2, "other"), "他班词库"
    )

    base = STUDENT.format(code=classroom["code"])
    resp = client.get(f"{base}/books", headers=student["headers"])
    assert resp.status_code == 200, resp.text
    titles = {b["title"] for b in resp.json()}
    assert public_title in titles
    assert mine["title"] in titles
    assert "他班词库" not in titles

    # 名称搜索
    resp = client.get(
        f"{base}/books", params={"search": public_title}, headers=student["headers"]
    )
    assert {b["title"] for b in resp.json()} == {public_title}

    # 归档词库不可见
    resp = client.patch(
        f"{VOCAB}/books/{mine['id']}",
        json={"status": "archived"},
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.get(f"{base}/books", headers=student["headers"])
    assert mine["title"] not in {b["title"] for b in resp.json()}

    # 他班学生访问本班词库详情 → 403
    other_student = make_student(db, client, other_classroom["code"])
    resp = client.get(
        f"{STUDENT.format(code=other_classroom['code'])}/books/{mine['id']}",
        headers=other_student["headers"],
    )
    assert resp.status_code == 403, resp.text


def test_student_book_word_search(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """库内搜索覆盖拼写/中文释义/英文释义；未登录 401。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(
        client,
        teacher_headers,
        classroom["id"],
        [
            {"headword": "apple", "part_of_speech": "n.", "meaning_zh": "苹果"},
            {
                "headword": "banana",
                "part_of_speech": "n.",
                "meaning_zh": "香蕉",
                "meaning_en": "a long yellow fruit",
            },
        ],
    )
    base = STUDENT.format(code=classroom["code"])
    resp = client.get(
        f"{base}/books/{book['id']}",
        params={"search": "香"},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert [w["headword"] for w in resp.json()["words"]] == ["banana"]
    resp = client.get(
        f"{base}/books/{book['id']}",
        params={"search": "BANANA"},
        headers=student["headers"],
    )
    assert [w["headword"] for w in resp.json()["words"]] == ["banana"]
    resp = client.get(
        f"{base}/books/{book['id']}",
        params={"search": "yellow fruit"},
        headers=student["headers"],
    )
    assert [w["headword"] for w in resp.json()["words"]] == ["banana"]
    assert client.get(f"{base}/books/{book['id']}").status_code == 401


# ── 自主开轮：默认 20 词 / 实际数量 / 题单固化 / 与任务独立 ──────────


def test_self_session_word_count_and_fixation(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """默认 20 词、不足按实际数量；题单与题序创建后固定（刷新稳定）。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(25))

    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    assert created["total_count"] == 20
    assert created["kind"] == "self"
    assert created["wrong_word_count"] == 0

    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    assert plan["total_count"] == 20
    assert plan["status"] == "in_progress"
    assert plan["started_at"] is not None
    # 未答题不透露拼写
    assert all(item["headword"] is None for item in plan["items"])
    assert all(item["answered"] is False for item in plan["items"])
    order_before = [(i["item_index"], i["meaning_zh"]) for i in plan["items"]]

    # 刷新再拉：同一会话、同一题单与题序
    plan_again = _plan(
        client, student["headers"], classroom["code"], created["session_id"]
    )
    assert [(i["item_index"], i["meaning_zh"]) for i in plan_again["items"]] == (
        order_before
    )

    # 未结束的同款轮次续做（重复点击/刷新不产生重复轮次）
    created_again = _start_self(
        client, student["headers"], classroom["code"], book["id"]
    )
    assert created_again["session_id"] == created["session_id"]

    # 词数不足按实际数量
    small_book = _make_class_book(
        client, teacher_headers, classroom["id"], _words(3, "s"), "小词库"
    )
    small = _start_self(client, student["headers"], classroom["code"], small_book["id"])
    assert small["total_count"] == 3

    # 空词库 → 422；缺 book_id → 422；超上限 → 422
    empty_book = _make_class_book(
        client, teacher_headers, classroom["id"], [], "空词库"
    )
    base = STUDENT.format(code=classroom["code"])
    assert (
        client.post(
            f"{base}/sessions",
            json={"kind": "self", "book_id": empty_book["id"]},
            headers=student["headers"],
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/sessions", json={"kind": "self"}, headers=student["headers"]
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{base}/sessions",
            json={"kind": "self", "book_id": book["id"], "word_count": 101},
            headers=student["headers"],
        ).status_code
        == 422
    )


def test_self_practice_answers_and_task_independence(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """自主轮作答可用既有机制；练相同词库不产生教师任务进度与成绩。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(5))
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )

    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    session_id = created["session_id"]
    plan = _plan(client, student["headers"], classroom["code"], session_id)
    by_meaning = {i["meaning_zh"]: i["item_index"] for i in plan["items"]}
    # 首答 1 错 1 对
    first = _answer(client, student["headers"], session_id, by_meaning["词1"], "xxxxx")
    assert first["is_correct"] is False
    assert first["correct_spelling"] == "w01"  # 已答即揭示正确拼写
    second = _answer(client, student["headers"], session_id, by_meaning["词2"], "w02")
    assert second["is_correct"] is True

    # 教师用同一词库发布任务：任务进度不受自主轮影响
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
        json={"word_ids": word_ids, "prompt_types": ["meaning"]},
        headers=teacher_headers,
    ).json()
    today = client.get(
        TODAY.format(code=classroom["code"]), headers=student["headers"]
    ).json()
    row = next(
        r for r in today["assignments"] if r["assignment_id"] == assignment["id"]
    )
    assert row["progress"] == "not_started"
    assert row["answered_count"] == 0

    # 自主轮答完 → 完成；任务进度仍是 not_started
    plan = _plan(client, student["headers"], classroom["code"], session_id)
    _finish_round(client, student["headers"], session_id, plan, spelling)
    plan = _plan(client, student["headers"], classroom["code"], session_id)
    assert plan["status"] == "submitted"
    assert plan["submitted_at"] is not None
    today = client.get(
        TODAY.format(code=classroom["code"]), headers=student["headers"]
    ).json()
    row = next(
        r for r in today["assignments"] if r["assignment_id"] == assignment["id"]
    )
    assert row["progress"] == "not_started"

    # 任务归档后自主轮仍可开（不受任务截止门禁影响）
    client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments/{assignment['id']}/archive",
        headers=teacher_headers,
    )
    another = _start_self(client, student["headers"], classroom["code"], book["id"])
    assert another["session_id"] != session_id  # 上一轮已结束，新开一轮


# ── 混入错词 ───────────────────────────────────────────────────────


def test_self_session_mix_wrong_words(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """混错词：30% 目标、最近错误优先、只取所选词库、不足补足、默认关闭。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(30))

    # 每轮错一个词（w01→w04，时间递增），其余答对
    for headword in ("w01", "w02", "w03", "w04"):
        _seed_wrong_words(
            client, student["headers"], classroom["code"], book["id"], [headword]
        )

    created = _start_self(
        client,
        student["headers"],
        classroom["code"],
        book["id"],
        word_count=10,
        mix_wrong=True,
    )
    # 目标 30% → 3 个错词：取最近错误的 w04/w03/w02（不是最早的 w01）
    assert created["total_count"] == 10
    assert created["wrong_word_count"] == 3
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    from_wrong = [i for i in plan["items"] if i["from_wrong"]]
    assert len(from_wrong) == 3
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )
    picked = {spelling[i["meaning_zh"]] for i in from_wrong}
    assert picked == {"w02", "w03", "w04"}

    # 题单固化：再拉一次题序不变
    plan_again = _plan(
        client, student["headers"], classroom["code"], created["session_id"]
    )
    assert [(i["item_index"], i["meaning_zh"]) for i in plan_again["items"]] == [
        (i["item_index"], i["meaning_zh"]) for i in plan["items"]
    ]
    # 答完混错轮，后续开轮不再续做该轮
    _finish_round(client, student["headers"], created["session_id"], plan, spelling)

    # 错词池只有 1 个：混 1 个、其余以其他词补足
    solo_book = _make_class_book(
        client, teacher_headers, classroom["id"], _words(10, "s"), "单错词库"
    )
    _seed_wrong_words(
        client, student["headers"], classroom["code"], solo_book["id"], ["s01"]
    )
    solo = _start_self(
        client,
        student["headers"],
        classroom["code"],
        solo_book["id"],
        word_count=6,
        mix_wrong=True,
    )
    assert solo["total_count"] == 6
    assert solo["wrong_word_count"] == 1

    # 默认关闭：不指定 mix_wrong 时无错词混入
    plain = _start_self(
        client, student["headers"], classroom["code"], book["id"], word_count=8
    )
    assert plain["wrong_word_count"] == 0

    # 只取所选词库内的错词：无错词的词库开混错轮 → 0 个
    other_book = _make_class_book(
        client, teacher_headers, classroom["id"], _words(6, "o"), "无错词库"
    )
    empty_mix = _start_self(
        client,
        student["headers"],
        classroom["code"],
        other_book["id"],
        word_count=6,
        mix_wrong=True,
    )
    assert empty_mix["wrong_word_count"] == 0


def test_mix_wrong_dedup_and_homographs(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """同词多次拼错只混一次（按词条去重）；同形异义两个词条都可独立混入。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(
        client,
        teacher_headers,
        classroom["id"],
        [
            {"headword": "bank", "meaning_zh": "银行"},
            {"headword": "bank", "meaning_zh": "河岸"},
            {"headword": "lead", "meaning_zh": "带领"},
            {"headword": "lead", "meaning_zh": "铅"},
            {"headword": "mile", "meaning_zh": "英里"},
            {"headword": "noun", "meaning_zh": "名词"},
        ],
    )
    spelling = {
        "银行": "bank",
        "河岸": "bank",
        "带领": "lead",
        "铅": "lead",
        "英里": "mile",
        "名词": "noun",
    }
    # 两轮各把两个 bank 词条拼错 → 各自历史错误次数累计到 2
    for _ in range(2):
        created = _start_self(
            client, student["headers"], classroom["code"], book["id"], word_count=6
        )
        plan = _plan(
            client, student["headers"], classroom["code"], created["session_id"]
        )
        by_meaning = {i["meaning_zh"]: i for i in plan["items"]}
        _answer(
            client,
            student["headers"],
            created["session_id"],
            by_meaning["银行"]["item_index"],
            "bnak",
        )
        _answer(
            client,
            student["headers"],
            created["session_id"],
            by_meaning["河岸"]["item_index"],
            "bnak",
        )
        _finish_round(client, student["headers"], created["session_id"], plan, spelling)

    wrong_items = _wrong_words(client, student["headers"], classroom["code"])
    banks = [w for w in wrong_items if w["headword"] == "bank"]
    assert len(banks) == 2  # 同形异义：两个独立词条都在错词本
    assert all(w["wrong_count"] == 2 for w in banks)  # 多次拼错累计计数

    # 混错轮：两个 bank 词条同时混入（词条 ID 去重不合并同形异义）
    created = _start_self(
        client,
        student["headers"],
        classroom["code"],
        book["id"],
        word_count=6,
        mix_wrong=True,
    )
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    mixed = [i for i in plan["items"] if i["from_wrong"]]
    assert {i["meaning_zh"] for i in mixed} >= {"银行", "河岸"}
    meanings = [i["meaning_zh"] for i in plan["items"]]
    assert len(meanings) == len(set(meanings))  # 每个词条至多一次


# ── 错词本聚合与专项复习 ───────────────────────────────────────────


def test_wrong_word_book_persistence_and_correction(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """一次答对不删错词：历史错误次数不变，最近独立首答与最近答对分列。"""
    _teacher, _teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, _teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(
        client,
        _teacher_headers,
        classroom["id"],
        [
            {"headword": "receive", "meaning_zh": "收到"},
            {"headword": "believe", "meaning_zh": "相信"},
        ],
    )
    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    by_meaning = {i["meaning_zh"]: i["item_index"] for i in plan["items"]}
    # receive 首答错（进错词本）；believe 首答错、同轮重试答对
    _answer(
        client, student["headers"], created["session_id"], by_meaning["收到"], "recieve"
    )
    _answer(
        client, student["headers"], created["session_id"], by_meaning["相信"], "beleive"
    )
    _answer(
        client, student["headers"], created["session_id"], by_meaning["相信"], "believe"
    )

    items = {
        w["headword"]: w
        for w in _wrong_words(client, student["headers"], classroom["code"])
    }
    assert set(items) == {"receive", "believe"}
    believe = items["believe"]
    assert believe["wrong_count"] == 1  # 重试答对不冲抵历史错误次数
    assert believe["last_first_is_correct"] is False  # 最近独立首答仍是错的
    assert believe["last_correct_at"] is not None  # 但有最近练对证据
    receive = items["receive"]
    assert receive["last_correct_at"] is None
    assert receive["practiceable"] is True

    # 下一轮独立首答答对：wrong_count 不变、last_first_is_correct=True
    created2 = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan2 = _plan(client, student["headers"], classroom["code"], created2["session_id"])
    by_meaning2 = {i["meaning_zh"]: i["item_index"] for i in plan2["items"]}
    _answer(
        client,
        student["headers"],
        created2["session_id"],
        by_meaning2["收到"],
        "receive",
    )
    items = {
        w["headword"]: w
        for w in _wrong_words(client, student["headers"], classroom["code"])
    }
    receive = items["receive"]
    assert receive["wrong_count"] == 1  # 不删除、不冲抵
    assert receive["last_first_is_correct"] is True
    assert receive["last_correct_at"] is not None


def test_review_session_scope_and_order(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """错词专项：只练当前可练词库内的错词、最近错误优先；无错词 422。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])

    # 无错词 → 422
    base = STUDENT.format(code=classroom["code"])
    assert (
        client.post(
            f"{base}/sessions", json={"kind": "review"}, headers=student["headers"]
        ).status_code
        == 422
    )

    book_a = _make_class_book(
        client, teacher_headers, classroom["id"], _words(4, "a"), "词库A"
    )
    book_b = _make_class_book(
        client, teacher_headers, classroom["id"], _words(4, "b"), "词库B"
    )
    # 错词时间序：a01 → a02 → b01（最近）
    for headword in ("a01", "a02"):
        _seed_wrong_words(
            client, student["headers"], classroom["code"], book_a["id"], [headword]
        )
    _seed_wrong_words(
        client, student["headers"], classroom["code"], book_b["id"], ["b01"]
    )

    created = _start_review(client, student["headers"], classroom["code"])
    # word_count 默认 20 > 错词 3 个 → 按实际数量
    assert created["total_count"] == 3
    assert created["wrong_word_count"] == 3
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    assert all(i["from_wrong"] for i in plan["items"])
    # 最近错误优先：b01（最近）在前，然后 a02、a01（a01/a02 释义同为 词1/词2，
    # 用位置顺序断言）
    assert [i["meaning_zh"] for i in plan["items"]] == ["词1", "词2", "词1"]
    # 答完这轮复习（最近优先顺序 b01/a02/a01），后续开轮不再续做
    for item, headword in zip(plan["items"], ["b01", "a02", "a01"], strict=True):
        _answer(
            client,
            student["headers"],
            created["session_id"],
            item["item_index"],
            headword,
        )

    # 限定授权范围：词库A 归档后，其中 2 个错词不能再进复习
    client.patch(
        f"{VOCAB}/books/{book_a['id']}",
        json={"status": "archived"},
        headers=teacher_headers,
    )
    items = _wrong_words(client, student["headers"], classroom["code"])
    practiceable = {w["headword"]: w["practiceable"] for w in items}
    assert practiceable["a01"] is False
    assert practiceable["b01"] is True
    review = _start_review(client, student["headers"], classroom["code"])
    assert review["total_count"] == 1  # 只剩词库B 的 b01

    # 复习轮首答答对 → 错词本证据更新（不删除）
    plan = _plan(client, student["headers"], classroom["code"], review["session_id"])
    _answer(
        client,
        student["headers"],
        review["session_id"],
        plan["items"][0]["item_index"],
        "b01",
    )
    by_head = {
        w["headword"]: w
        for w in _wrong_words(client, student["headers"], classroom["code"])
    }
    assert by_head["b01"]["last_first_is_correct"] is True
    assert by_head["b01"]["wrong_count"] == 1


# ── 历史列表与单次详情 ─────────────────────────────────────────────


def test_history_list_and_detail(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """历史统一三类轮次（kind 区分）；详情回填首答输入、未答不透露拼写。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    other_student = make_student(db, client, classroom["code"], name="同学")
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(3))
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )

    # 任务轮：发布 + 答一题
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
        json={"word_ids": word_ids, "prompt_types": ["meaning"]},
        headers=teacher_headers,
    )
    resp = client.post(
        "/api/v1/classes/{code}/vocabulary/sessions".replace(
            "{code}", classroom["code"]
        ),
        json={},
        headers=student["headers"],
    )
    task_session = resp.json()["session_id"]
    _answer(client, student["headers"], task_session, 0, spelling["词1"])

    # 自主轮：答一题对、答一题错
    self_created = _start_self(
        client, student["headers"], classroom["code"], book["id"]
    )
    self_plan = _plan(
        client, student["headers"], classroom["code"], self_created["session_id"]
    )
    by_meaning = {i["meaning_zh"]: i["item_index"] for i in self_plan["items"]}
    _answer(
        client,
        student["headers"],
        self_created["session_id"],
        by_meaning["词1"],
        "w01",
    )
    _answer(
        client,
        student["headers"],
        self_created["session_id"],
        by_meaning["词2"],
        "wrong",
    )

    history = _history(client, student["headers"], classroom["code"])
    kinds = {(h["kind"], h.get("round_no")) for h in history}
    assert ("task", 1) in kinds
    assert ("self", None) in kinds
    task_row = next(h for h in history if h["kind"] == "task")
    self_row = next(h for h in history if h["kind"] == "self")
    assert task_row["answered_count"] == 1
    assert task_row["title"]
    assert self_row["book_id"] == book["id"]
    # 未开始的同学没有历史
    assert _history(client, other_student["headers"], classroom["code"]) == []

    # 自主轮详情：已答回填拼写与本人首答输入；未答不透露
    plan = _plan(
        client, student["headers"], classroom["code"], self_created["session_id"]
    )
    answered = [i for i in plan["items"] if i["answered"]]
    unanswered = [i for i in plan["items"] if not i["answered"]]
    assert len(answered) == 2
    wrong_answered = next(i for i in answered if i["is_correct"] is False)
    assert wrong_answered["first_answer"] == "wrong"
    assert wrong_answered["headword"]  # 正确拼写已揭示
    right_answered = next(i for i in answered if i["is_correct"] is True)
    assert right_answered["first_answer"] == "w01"
    assert all(i["headword"] is None and i["first_answer"] is None for i in unanswered)

    # 同学访问他人详情 → 404
    resp = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{self_created['session_id']}",
        headers=other_student["headers"],
    )
    assert resp.status_code == 404, resp.text

    # 报告口径字段：计数下发（正确率/进度由前端按口径计算）+ 起止时间
    assert plan["answered_count"] == 2
    assert plan["correct_first_count"] == 1
    assert plan["total_count"] == 3
    assert plan["started_at"] is not None


# ── 评审回归（PR#74 第一轮审核）────────────────────────────────────


def _seed_many_wrong_via_task(
    client: TestClient,
    teacher_headers: dict[str, str],
    student_headers: dict[str, str],
    code: str,
    book_id: str,
    wrong_headwords: set[str],
) -> None:
    """发布一个任务并把其中指定词的首答全部拼错（一轮制造多个错词）。"""
    word_ids = [
        w["id"]
        for w in client.get(f"{VOCAB}/books/{book_id}", headers=teacher_headers).json()[
            "words"
        ]
    ]
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments",
        json={"word_ids": word_ids, "prompt_types": ["meaning"]},
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions", json={}, headers=student_headers
    )
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    plan = client.get(TODAY.format(code=code), headers=student_headers).json()
    spelling = _spelling_by_meaning(client, student_headers, code, book_id)
    for item in plan["items"]:
        headword = spelling[item["meaning_zh"]]
        answer = f"z{headword}" if headword in wrong_headwords else headword
        _answer(client, student_headers, session_id, item["item_index"], answer)


def test_concurrent_self_start_creates_single_round(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """并发开同款自主轮：部分唯一索引兜底，只产生一个进行中会话。"""
    from concurrent.futures import ThreadPoolExecutor

    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(25))
    base = STUDENT.format(code=classroom["code"])

    def start() -> dict:
        resp = client.post(
            f"{base}/sessions",
            json={"kind": "self", "book_id": book["id"]},
            headers=student["headers"],
        )
        return {"status": resp.status_code, "body": resp.json()}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert all(o["status"] == 200 for o in outcomes), outcomes
    assert len({o["body"]["session_id"] for o in outcomes}) == 1


def test_concurrent_review_start_creates_single_round(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """并发开错词复习：同样只有一个进行中会话。"""
    from concurrent.futures import ThreadPoolExecutor

    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(5))
    _seed_wrong_words(
        client, student["headers"], classroom["code"], book["id"], ["w01"]
    )
    base = STUDENT.format(code=classroom["code"])

    def start() -> dict:
        resp = client.post(
            f"{base}/sessions",
            json={"kind": "review"},
            headers=student["headers"],
        )
        return {"status": resp.status_code, "body": resp.json()}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert all(o["status"] == 200 for o in outcomes), outcomes
    assert len({o["body"]["session_id"] for o in outcomes}) == 1


def test_mix_wrong_fill_prefers_plain_words(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """混练补位优先非错词：普通词充足时，混入占比恒等于目标、不多不少。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(20, "x"))
    # 一轮任务把 x01..x10 全部拼错（历史错词池 10 个），x11..x20 从未错过
    _seed_many_wrong_via_task(
        client,
        teacher_headers,
        student["headers"],
        classroom["code"],
        book["id"],
        {f"x{i:02d}" for i in range(1, 11)},
    )
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )
    wrong_meanings = {
        m for m, h in spelling.items() if h in {f"x{i:02d}" for i in range(1, 11)}
    }

    created = _start_self(
        client,
        student["headers"],
        classroom["code"],
        book["id"],
        word_count=10,
        mix_wrong=True,
    )
    # 目标 30% → 恰好 3 个错词；其余 7 个必须是普通词（不得混入其余错词）
    assert created["total_count"] == 10
    assert created["wrong_word_count"] == 3
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    marked = [i for i in plan["items"] if i["from_wrong"]]
    plain = [i for i in plan["items"] if not i["from_wrong"]]
    assert len(marked) == 3
    assert all(i["meaning_zh"] in wrong_meanings for i in marked)
    assert len(plain) == 7
    assert all(i["meaning_zh"] not in wrong_meanings for i in plain)


def test_mix_wrong_overflow_marks_extra_wrong(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """非错词不足时用其余错词补足，且这些词同样计入错词标记（口径一致）。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(4, "y"))
    # 3 个错词 + 1 个普通词；请求 4 题、开混练：目标 30% → 1 个，
    # 普通词只有 1 个，剩余 2 题只能用其余错词补足（应标记 from_wrong）
    _seed_many_wrong_via_task(
        client,
        teacher_headers,
        student["headers"],
        classroom["code"],
        book["id"],
        {"y01", "y02", "y03"},
    )
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )
    wrong_meanings = {m for m, h in spelling.items() if h in {"y01", "y02", "y03"}}

    created = _start_self(
        client,
        student["headers"],
        classroom["code"],
        book["id"],
        word_count=4,
        mix_wrong=True,
    )
    assert created["total_count"] == 4
    assert created["wrong_word_count"] == 3  # 1 个目标错词 + 2 个补足错词
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    marked = [i for i in plan["items"] if i["from_wrong"]]
    assert len(marked) == 3
    assert {i["meaning_zh"] for i in marked} == wrong_meanings
    assert len([i for i in plan["items"] if not i["from_wrong"]]) == 1


def test_archived_word_not_practiceable_and_not_in_review(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """已归档词条不能再进复习轮：practiceable=false，复习池排除它。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2, "a"))
    _seed_wrong_words(
        client, student["headers"], classroom["code"], book["id"], ["a01"]
    )
    _seed_wrong_words(
        client, student["headers"], classroom["code"], book["id"], ["a02"]
    )
    # 归档词条 a01（词库仍 active）
    words = client.get(f"{VOCAB}/books/{book['id']}", headers=teacher_headers).json()[
        "words"
    ]
    a01_id = next(w["id"] for w in words if w["headword"] == "a01")
    resp = client.patch(
        f"{VOCAB}/words/{a01_id}",
        json={"status": "archived"},
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text

    # 词库浏览不再返回 a01
    remaining = client.get(
        f"{STUDENT.format(code=classroom['code'])}/books/{book['id']}",
        headers=student["headers"],
    ).json()["words"]
    assert {w["headword"] for w in remaining} == {"a02"}

    items = {
        w["headword"]: w
        for w in _wrong_words(client, student["headers"], classroom["code"])
    }
    assert items["a01"]["practiceable"] is False  # 历史错词保留，只标不可练
    assert items["a02"]["practiceable"] is True

    # 新复习轮只含 a02
    review = _start_review(client, student["headers"], classroom["code"])
    plan = _plan(client, student["headers"], classroom["code"], review["session_id"])
    assert {i["meaning_zh"] for i in plan["items"]} == {"词2"}


def test_last_correct_at_includes_history_before_first_wrong(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """首次判错之前的答对记录也是「最近练对」证据（单词条先对后错）。"""
    _teacher, _teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, _teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(
        client,
        _teacher_headers,
        classroom["id"],
        [{"headword": "orbit", "meaning_zh": "轨道"}],
    )
    # 第一轮首答答对（不进错词本）
    first = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _plan(client, student["headers"], classroom["code"], first["session_id"])
    _answer(
        client,
        student["headers"],
        first["session_id"],
        plan["items"][0]["item_index"],
        "orbit",
    )
    # 第二轮首答判错（进错词本）
    second = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan2 = _plan(client, student["headers"], classroom["code"], second["session_id"])
    _answer(
        client,
        student["headers"],
        second["session_id"],
        plan2["items"][0]["item_index"],
        "oribt",
    )
    items = _wrong_words(client, student["headers"], classroom["code"])
    assert len(items) == 1
    entry = items[0]
    assert entry["headword"] == "orbit"
    assert entry["wrong_count"] == 1
    assert entry["last_first_is_correct"] is False
    # 第一轮的答对时间不能丢
    assert entry["last_correct_at"] is not None
