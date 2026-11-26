"""课堂实时 PK 闭环测试：权限、配对、题单一致性、幂等、断线恢复、超时结算、
跨班隔离、口径分离（不写 VocabularyAnswer）与 SSE 冒烟。

口径约束（设计稿 docs/vocabulary-pk-farm-design-20261122.md §2/§3）：
- 班内自愿：仅本课堂成员/本班教师可读；学生不能开大厅；跨班 404。
- 口径分离：PK 作答只落 vocab_pk_answer，不产生 VocabularyAnswer、不改任务统计。
- 判分：每题首答有效；同幂等键重放返回首次结果，不二次计分。
"""

import time
import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import (
    MAX_QUEUE_PLAYERS,
    User,
    VocabPkAnswer,
    VocabPkMatch,
    VocabPkPlayer,
    VocabularyAnswer,
)
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

PK = "/api/v1/classes/{code}/vocabulary/pk"


def _login_teacher(db: Session, client: TestClient):
    email, password = random_email(), random_lower_string()
    from app import crud
    from app.models import UserCreate

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
    resp = client.post("/api/v1/classes", json={"class_size": 30}, headers=headers)
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


def _open_lobby(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    book_id: str,
    *,
    question_count: int = 4,
    per_question_seconds: int = 20,
    prompt_types: list[str] | None = None,
) -> dict:
    body: dict = {
        "book_id": book_id,
        "question_count": question_count,
        "per_question_seconds": per_question_seconds,
    }
    if prompt_types is not None:
        body["prompt_types"] = prompt_types
    resp = client.post(f"{PK.format(code=code)}/lobby", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.post(f"{PK.format(code=code)}/lobby/join", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _spelling_map(
    client: TestClient, headers: dict[str, str], book_id: str
) -> dict[str, str]:
    resp = client.get(f"/api/v1/vocabulary/books/{book_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return {w["meaning_zh"]: w["headword"] for w in resp.json()["words"]}


def _answer(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    match_id: str,
    item_index: int,
    answer: str,
    idempotency_key: str | None = None,
    prompt_type: str = "meaning",
) -> dict:
    body: dict = {
        "item_index": item_index,
        "prompt_type": prompt_type,
        "answer": answer,
    }
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    resp = client.post(
        f"{PK.format(code=code)}/matches/{match_id}/answers",
        json=body,
        headers=headers,
    )
    return resp.json() | {"_status": resp.status_code}


def _match(
    client: TestClient, headers: dict[str, str], code: str, match_id: str
) -> dict:
    resp = client.get(f"{PK.format(code=code)}/matches/{match_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 权限 ──────────────────────────────────────────────────────────────


def test_student_cannot_open_lobby(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "s"), "s1")
    student = make_student(db, client, classroom["code"])

    resp = client.post(
        f"{PK.format(code=classroom['code'])}/lobby",
        json={"book_id": book["id"], "question_count": 4},
        headers=student["headers"],
    )
    assert resp.status_code == 403, resp.text


def test_cross_classroom_student_cannot_read_lobby(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    other_teacher, other_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    other_classroom = _create_classroom(client, other_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "x"), "x1")
    _open_lobby(client, teacher_headers, classroom["code"], book["id"])
    outsider = make_student(db, client, other_classroom["code"])

    resp = client.get(
        f"{PK.format(code=classroom['code'])}/lobby", headers=outsider["headers"]
    )
    assert resp.status_code == 404, resp.text


# ── 配对 / 题单一致性 / 判分 / 结算 ──────────────────────────────────


def test_pairing_consistent_snapshot_scoring_and_settlement(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "p"), "p1")
    spelling = _spelling_map(client, teacher_headers, book["id"])
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=4,
        prompt_types=["meaning"],
    )

    a = make_student(db, client, classroom["code"], "学生甲")
    b = make_student(db, client, classroom["code"], "学生乙")
    answers_before = len(db.exec(select(VocabularyAnswer)).all())
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])

    match_id = lobby_b["my_match_id"]
    assert match_id is not None

    view_a = _match(client, a["headers"], classroom["code"], match_id)
    view_b = _match(client, b["headers"], classroom["code"], match_id)

    # 双方题单完全一致（题序、题面、选项固化在对局内）
    assert [i["meaning_zh"] for i in view_a["items"]] == [
        i["meaning_zh"] for i in view_b["items"]
    ]
    assert view_a["question_count"] == 4

    # 甲答对前两题、后两题答错；乙全部答对（双方都答满后结算）
    plan = view_a["items"]
    for idx, item in enumerate(plan):
        answer = spelling[item["meaning_zh"]]
        a_answer = answer if idx < 2 else f"x{answer}"
        res = _answer(client, a["headers"], classroom["code"], match_id, idx, a_answer)
        assert res["_status"] == 200, res
        assert res["is_correct"] is (idx < 2)
        res_b = _answer(client, b["headers"], classroom["code"], match_id, idx, answer)
        assert res_b["_status"] == 200, res_b

    final = _match(client, b["headers"], classroom["code"], match_id)
    assert final["status"] == "finished"
    assert final["result"]["winner_student_id"] == b["student"]["id"]
    assert final["result"]["drew"] is False

    # 口径分离：PK 不产生 VocabularyAnswer，不改任务统计
    answers_after = len(db.exec(select(VocabularyAnswer)).all())
    assert answers_after == answers_before
    pk_answers = db.exec(select(VocabPkAnswer)).all()
    assert len(pk_answers) == 8  # 双方各 4 题


def test_idempotent_replay_no_double_score(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "i"), "i1")
    spelling = _spelling_map(client, teacher_headers, book["id"])
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=4,
        prompt_types=["meaning"],
    )
    a = make_student(db, client, classroom["code"], "甲")
    b = make_student(db, client, classroom["code"], "乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]

    item = _match(client, a["headers"], classroom["code"], match_id)["items"][0]
    answer = spelling[item["meaning_zh"]]
    key = f"pk-key-{uuid.uuid4().hex[:8]}"
    first = _answer(
        client,
        a["headers"],
        classroom["code"],
        match_id,
        0,
        answer,
        idempotency_key=key,
    )
    assert first["_status"] == 200, first
    score_after_first = first["my_score"]

    replay = _answer(
        client,
        a["headers"],
        classroom["code"],
        match_id,
        0,
        answer,
        idempotency_key=key,
    )
    assert replay["_status"] == 200, replay
    assert replay["replayed"] is True
    assert replay["my_score"] == score_after_first

    # 同题第二次非重放提交 → 422
    dup = _answer(
        client, a["headers"], classroom["code"], match_id, 0, f"wrong{answer}"
    )
    assert dup["_status"] == 422, dup

    # 同键不同答案 → 422（客户端误用，不得返回旧作答）
    conflict = _answer(
        client,
        a["headers"],
        classroom["code"],
        match_id,
        1,
        "whatever",
        idempotency_key=key,
    )
    assert conflict["_status"] == 422, conflict


def test_reconnect_restores_question_clock_and_score(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "r"), "r1")
    spelling = _spelling_map(client, teacher_headers, book["id"])
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=4,
        prompt_types=["meaning"],
        per_question_seconds=30,
    )
    a = make_student(db, client, classroom["code"], "甲")
    b = make_student(db, client, classroom["code"], "乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]

    item = _match(client, a["headers"], classroom["code"], match_id)["items"][0]
    answer = spelling[item["meaning_zh"]]
    res = _answer(client, a["headers"], classroom["code"], match_id, 0, answer)
    assert res["_status"] == 200, res

    # 断线重连：按 match_id 恢复当前题、剩余时间与比分
    view = _match(client, a["headers"], classroom["code"], match_id)
    assert view["me"]["answered_count"] == 1
    assert view["me"]["score"] == res["my_score"]
    assert view["current_item_index"] == 1
    assert view["remaining_seconds"] is not None
    assert view["remaining_seconds"] <= 30


def test_en_zh_prompt_exposes_headword_before_answer(
    client: TestClient, db: Session
) -> None:
    """PK 的 en_zh 题面必须给英文 headword；zh_en 作答前不能泄题。

    回归背景：前端已按题型读 headword，但后端 _item_view 只在已作答时透出，
    导致真机 en_zh 题面回退成中文释义。
    """
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "p"), "p1")
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=4,
        prompt_types=["en_zh", "zh_en"],
    )
    a = make_student(db, client, classroom["code"], "甲")
    b = make_student(db, client, classroom["code"], "乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]

    items = _match(client, a["headers"], classroom["code"], match_id)["items"]
    by_type = {item["prompt_type"]: item for item in items}
    assert by_type["en_zh"]["headword"]
    assert by_type["en_zh"]["answered"] is False
    assert by_type["zh_en"]["headword"] is None


def test_timeout_settles_unanswered_as_zero(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "t"), "t1")
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=1,
        prompt_types=["meaning"],
        per_question_seconds=1,
    )
    a = make_student(db, client, classroom["code"], "甲")
    b = make_student(db, client, classroom["code"], "乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]

    time.sleep(1.6)
    # GET 只读：超时不会被读路径结算，对局仍保持 active
    peek = _match(client, a["headers"], classroom["code"], match_id)
    assert peek["status"] == "active"
    # 写路径（作答尝试）触发超时收口并 commit 结算；终局后作答被 422 拒绝
    attempt = _answer(client, a["headers"], classroom["code"], match_id, 0, "whatever")
    assert attempt["_status"] == 422, attempt

    view = _match(client, a["headers"], classroom["code"], match_id)
    assert view["status"] == "finished"
    # 超时未答记 0；双方都未得分
    assert view["me"]["score"] == 0
    assert view["opponent"]["score"] == 0
    assert view["result"]["end_reason"] == "timeout"

    # 结算结果已落库：终局字段非空、平局无胜者
    db.expire_all()
    row = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row is not None
    assert row.status == "finished"
    assert row.finished_at is not None
    assert row.end_reason == "timeout"
    assert row.winner_student_id is None


def test_queue_capacity_limit(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "c"), "c1")
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=2,
        prompt_types=["meaning"],
    )

    students = [
        make_student(db, client, classroom["code"], f"玩家{i}")
        for i in range(MAX_QUEUE_PLAYERS)
    ]
    for student in students:
        resp = client.post(
            f"{PK.format(code=classroom['code'])}/lobby/join",
            headers=student["headers"],
        )
        assert resp.status_code == 200, resp.text

    overflow = make_student(db, client, classroom["code"], "溢出玩家")
    resp = client.post(
        f"{PK.format(code=classroom['code'])}/lobby/join",
        headers=overflow["headers"],
    )
    assert resp.status_code == 422, resp.text


def test_sse_stream_emits_state_snapshot(client: TestClient, db: Session) -> None:
    import asyncio

    from app.api.routes import vocabulary_pk as pk_routes

    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(8, "s"), "s2")
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=2,
        prompt_types=["meaning"],
    )
    a = make_student(db, client, classroom["code"], "甲")
    b = make_student(db, client, classroom["code"], "乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]

    async def _first_event():
        response = await pk_routes.pk_match_events(
            session=db,
            code=classroom["code"],
            match_id=uuid.UUID(match_id),
            current_user=a["user"],
        )
        agen = response.body_iterator
        first = await agen.__anext__()
        await agen.aclose()
        return response, first

    response, first = asyncio.run(_first_event())
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: state" in first
    assert "state_version" in first


def test_teacher_can_read_lobby_but_not_subscribe_match(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "q"), "q1")
    _open_lobby(client, teacher_headers, classroom["code"], book["id"])
    # 教师可读大厅
    resp = client.get(
        f"{PK.format(code=classroom['code'])}/lobby", headers=teacher_headers
    )
    assert resp.status_code == 200, resp.text

    a = make_student(db, client, classroom["code"], "甲")
    b = make_student(db, client, classroom["code"], "乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]
    # 教师不在对局玩家名单内 → 403（仅本局玩家可查看对局）
    resp = client.get(
        f"{PK.format(code=classroom['code'])}/matches/{match_id}",
        headers=teacher_headers,
    )
    assert resp.status_code == 403, resp.text


# ── D10：结算落库 / 只读视图 / 重复结算幂等 ──────────────────────────


def _setup_active_match(
    client: TestClient, db: Session, prefix: str, question_count: int = 4
) -> tuple[User, dict[str, str], dict, dict, dict, dict, dict, str]:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(
        client, teacher_headers, classroom["id"], _words(8, prefix), f"{prefix}1"
    )
    spelling = _spelling_map(client, teacher_headers, book["id"])
    _open_lobby(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=question_count,
        prompt_types=["meaning"],
    )
    a = make_student(db, client, classroom["code"], f"{prefix}甲")
    b = make_student(db, client, classroom["code"], f"{prefix}乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]
    assert match_id is not None
    return teacher, teacher_headers, classroom, book, spelling, a, b, match_id


def _answer_all(
    client: TestClient,
    code: str,
    spelling: dict[str, str],
    a: dict,
    b: dict,
    match_id: str,
    question_count: int,
) -> None:
    """甲前两题对、后两题错；乙全对，双方答满后由写路径结算。"""
    view = client.get(
        f"{PK.format(code=code)}/matches/{match_id}", headers=b["headers"]
    ).json()
    for idx, item in enumerate(view["items"][:question_count]):
        answer = spelling[item["meaning_zh"]]
        a_answer = answer if idx < 2 else f"x{answer}"
        res = _answer(client, a["headers"], code, match_id, idx, a_answer)
        assert res["_status"] == 200, res
        res_b = _answer(client, b["headers"], code, match_id, idx, answer)
        assert res_b["_status"] == 200, res_b


def test_finished_match_settlement_persisted_to_db(
    client: TestClient, db: Session
) -> None:
    """双方答满终局后，DB 落库 status/winner/end_reason/finished_at；重复读不覆盖。"""
    teacher, headers, classroom, _book, spelling, a, b, match_id = _setup_active_match(
        client, db, "d10"
    )
    _answer_all(client, classroom["code"], spelling, a, b, match_id, 4)

    db.expire_all()
    row = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row is not None
    assert row.status == "finished"
    assert row.finished_at is not None
    assert row.end_reason == "completion"
    assert row.winner_student_id == uuid.UUID(b["student"]["id"])

    players = db.exec(
        select(VocabPkPlayer).where(VocabPkPlayer.match_id == uuid.UUID(match_id))
    ).all()
    by_student = {p.student_id: p for p in players}
    winner = by_student[uuid.UUID(b["student"]["id"])]
    loser = by_student[uuid.UUID(a["student"]["id"])]
    assert winner.status == "finished"
    assert winner.finished_at is not None
    assert loser.status == "finished"
    assert loser.finished_at is not None
    assert winner.score > loser.score

    # 重复 GET（轮询/快照读路径）不改变 winner 与结果
    for _ in range(3):
        view = _match(client, b["headers"], classroom["code"], match_id)
        assert view["status"] == "finished"
        assert view["result"]["winner_student_id"] == b["student"]["id"]
    db.expire_all()
    row2 = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row2 is not None
    assert row2.winner_student_id == uuid.UUID(b["student"]["id"])

    # 重复结算幂等：不再覆盖已写入的 winner/end_reason
    from app.services import vocabulary_pk as pk_service

    assert pk_service._settle_if_over(db, row2) is False
    assert pk_service._settle_if_over(db, row2) is False
    assert row2.winner_student_id == uuid.UUID(b["student"]["id"])
    assert row2.end_reason == "completion"

    # 教师 pk/history 能查到已结束对局
    hist = client.get(
        f"{PK.format(code=classroom['code'])}/history", headers=headers
    ).json()
    assert len(hist["matches"]) == 1
    assert hist["matches"][0]["winner_student_id"] == b["student"]["id"]
    assert hist["matches"][0]["finished_at"] is not None


def test_match_view_get_does_not_write_db(client: TestClient, db: Session) -> None:
    """GET/轮询快照是只读路径：不推进题目、不改版本号、不落终局字段。"""
    _teacher, _headers, classroom, _book, _spelling, a, _b, match_id = (
        _setup_active_match(client, db, "ro")
    )
    db.expire_all()
    row = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row is not None
    before = (row.status, row.state_version, row.current_item_index, row.finished_at)

    for _ in range(3):
        _match(client, a["headers"], classroom["code"], match_id)
        client.get(f"{PK.format(code=classroom['code'])}/lobby", headers=a["headers"])

    db.expire_all()
    row2 = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row2 is not None
    after = (row2.status, row2.state_version, row2.current_item_index, row2.finished_at)
    assert after == before


def test_answer_after_finished_rejected_and_settlement_kept(
    client: TestClient, db: Session
) -> None:
    """终局后再次作答 → 422；已落库的结算不被回滚或覆盖。"""
    _teacher, _headers, classroom, _book, spelling, a, b, match_id = (
        _setup_active_match(client, db, "idm")
    )
    _answer_all(client, classroom["code"], spelling, a, b, match_id, 4)

    dup = _answer(client, a["headers"], classroom["code"], match_id, 0, "whatever")
    assert dup["_status"] == 422, dup

    db.expire_all()
    row = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row is not None
    assert row.status == "finished"
    assert row.winner_student_id == uuid.UUID(b["student"]["id"])
    assert row.end_reason == "completion"


def test_leave_mid_match_settles_walkover(client: TestClient, db: Session) -> None:
    """对局中一方离场：写路径结算弃权胜，另一方落库为胜者。"""
    _teacher, headers, classroom, _book, _spelling, a, b, match_id = (
        _setup_active_match(client, db, "wo")
    )
    resp = client.delete(
        f"{PK.format(code=classroom['code'])}/lobby/join", headers=a["headers"]
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    row = db.get(VocabPkMatch, uuid.UUID(match_id))
    assert row is not None
    assert row.status == "finished"
    assert row.finished_at is not None
    assert row.end_reason == "walkover"
    assert row.winner_student_id == uuid.UUID(b["student"]["id"])

    players = db.exec(
        select(VocabPkPlayer).where(VocabPkPlayer.match_id == uuid.UUID(match_id))
    ).all()
    by_student = {p.student_id: p for p in players}
    assert by_student[uuid.UUID(a["student"]["id"])].status == "left"
    winner = by_student[uuid.UUID(b["student"]["id"])]
    assert winner.status == "finished"
    assert winner.finished_at is not None

    hist = client.get(
        f"{PK.format(code=classroom['code'])}/history", headers=headers
    ).json()
    assert len(hist["matches"]) == 1
    assert hist["matches"][0]["winner_student_id"] == b["student"]["id"]
