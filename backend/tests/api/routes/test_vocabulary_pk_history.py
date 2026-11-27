"""教师端 PK 历史列表与课堂看板 PK 摘要（#517 D）后端测试。

口径守点：
- 历史只列已结束/已放弃对局，按 finished_at/created_at 倒序；进行中对局不进历史。
- 仅本班教师可读；学生 403，跨班/跨校 404，不泄露存在性。
- 看板 ``vocabulary_pk`` 为只读摘要；模块未开通时为 null，看板其余字段口径不变。
- 口径分离：PK 数据不写 ``VocabularyAnswer``，不影响任务首答/掌握度/趋势。
"""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.models import (
    TenantModule,
    User,
    UserCreate,
    VocabularyAnswer,
)
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

PK = "/api/v1/classes/{code}/vocabulary/pk"
BOARD = "/api/v1/classes/{code}/board"


def _login_teacher(db: Session, client: TestClient):
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
) -> dict:
    resp = client.post(
        f"{PK.format(code=code)}/lobby",
        json={
            "book_id": book_id,
            "question_count": question_count,
            "prompt_types": ["meaning"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.post(f"{PK.format(code=code)}/lobby/join", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _spelling_map(client: TestClient, headers: dict[str, str], book_id: str) -> dict:
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
) -> dict:
    resp = client.post(
        f"{PK.format(code=code)}/matches/{match_id}/answers",
        json={
            "item_index": item_index,
            "prompt_type": "meaning",
            "answer": answer,
        },
        headers=headers,
    )
    return resp.json() | {"_status": resp.status_code}


def _settle_match(
    client: TestClient,
    code: str,
    spelling: dict[str, str],
    a: dict,
    b: dict,
    match_id: str,
) -> None:
    """双方答满 4 题：甲前对两题，乙全对，结算出胜者。"""
    view = client.get(
        f"{PK.format(code=code)}/matches/{match_id}", headers=b["headers"]
    ).json()
    for idx, item in enumerate(view["items"]):
        answer = spelling[item["meaning_zh"]]
        a_answer = answer if idx < 2 else f"x{answer}"
        res = _answer(client, a["headers"], code, match_id, idx, a_answer)
        assert res["_status"] == 200, res
        res_b = _answer(client, b["headers"], code, match_id, idx, answer)
        assert res_b["_status"] == 200, res_b


def _finished_match_setup(
    client: TestClient, db: Session
) -> tuple[User, dict[str, str], dict, dict, tuple[dict, dict, str]]:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(
        client, teacher_headers, classroom["id"], _words(8, "h"), "历史词库"
    )
    spelling = _spelling_map(client, teacher_headers, book["id"])
    _open_lobby(client, teacher_headers, classroom["code"], book["id"])
    a = make_student(db, client, classroom["code"], "历史甲")
    b = make_student(db, client, classroom["code"], "历史乙")
    _join(client, a["headers"], classroom["code"])
    lobby_b = _join(client, b["headers"], classroom["code"])
    match_id = lobby_b["my_match_id"]
    assert match_id is not None
    _settle_match(client, classroom["code"], spelling, a, b, match_id)
    return teacher, teacher_headers, classroom, book, (a, b, match_id)


# ── 历史列表 ──────────────────────────────────────────────────────────


def test_history_lists_finished_match_with_players(
    client: TestClient, db: Session
) -> None:
    _teacher, headers, classroom, book, (a, b, match_id) = _finished_match_setup(
        client, db
    )

    resp = client.get(f"{PK.format(code=classroom['code'])}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["matches"]) == 1
    match = body["matches"][0]

    assert match["match_id"] == match_id
    assert match["lobby_id"] is not None
    assert match["status"] == "finished"
    assert match["question_count"] == 4
    assert match["per_question_seconds"] > 0
    assert match["book_id"] == book["id"]
    assert match["book_title"] == "历史词库"
    assert match["started_at"] is not None
    assert match["finished_at"] is not None
    assert match["end_reason"] == "completion"
    assert match["winner_student_id"] == b["student"]["id"]
    assert match["winner_display_name"] == "历史乙"

    players = {p["student_id"]: p for p in match["players"]}
    assert set(players) == {a["student"]["id"], b["student"]["id"]}
    winner = players[b["student"]["id"]]
    loser = players[a["student"]["id"]]
    assert winner["result"] == "win"
    assert loser["result"] == "lose"
    assert winner["display_name"] == "历史乙"
    assert winner["score"] > 0
    assert winner["correct_count"] == 4
    assert winner["answered_count"] == 4
    assert winner["total_seconds"] >= 0
    assert loser["correct_count"] == 2


def test_history_excludes_active_match(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, book, _ = _finished_match_setup(client, db)

    # 再开一局进行中（不答题）：历史列表仍只含已结算的第一局
    _open_lobby(client, headers, classroom["code"], book["id"])
    c = make_student(db, client, classroom["code"], "进行中丙")
    d = make_student(db, client, classroom["code"], "进行中丁")
    _join(client, c["headers"], classroom["code"])
    lobby_d = _join(client, d["headers"], classroom["code"])
    assert lobby_d["my_match_id"] is not None

    resp = client.get(f"{PK.format(code=classroom['code'])}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["matches"]) == 1


def test_history_empty_classroom(client: TestClient, db: Session) -> None:
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    resp = client.get(f"{PK.format(code=classroom['code'])}/history", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["matches"] == []


def test_history_limit_bounds(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, _book, _ = _finished_match_setup(client, db)

    bad_low = client.get(
        f"{PK.format(code=classroom['code'])}/history",
        params={"limit": 0},
        headers=headers,
    )
    assert bad_low.status_code == 422, bad_low.text
    bad_high = client.get(
        f"{PK.format(code=classroom['code'])}/history",
        params={"limit": 51},
        headers=headers,
    )
    assert bad_high.status_code == 422, bad_high.text

    ok = client.get(
        f"{PK.format(code=classroom['code'])}/history",
        params={"limit": 1},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["matches"]) <= 1


def test_history_student_forbidden(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, _book, (a, _b, _match_id) = _finished_match_setup(
        client, db
    )
    resp = client.get(
        f"{PK.format(code=classroom['code'])}/history", headers=a["headers"]
    )
    assert resp.status_code == 403, resp.text


def test_history_cross_classroom_404(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, _book, _ = _finished_match_setup(client, db)
    other_teacher, other_headers = _login_teacher(db, client)
    other_classroom = _create_classroom(client, other_headers)
    outsider = make_student(db, client, other_classroom["code"], "外班同学")

    resp = client.get(
        f"{PK.format(code=classroom['code'])}/history", headers=outsider["headers"]
    )
    assert resp.status_code == 404, resp.text
    resp_teacher = client.get(
        f"{PK.format(code=classroom['code'])}/history", headers=other_headers
    )
    assert resp_teacher.status_code == 404, resp_teacher.text


def test_history_does_not_write_task_answers(client: TestClient, db: Session) -> None:
    answers_before = len(db.exec(select(VocabularyAnswer)).all())
    _teacher, _headers, _classroom, _book, _ = _finished_match_setup(client, db)
    answers_after = len(db.exec(select(VocabularyAnswer)).all())
    assert answers_after == answers_before


# ── 课堂看板 PK 摘要 ──────────────────────────────────────────────────


def test_board_pk_summary_after_finished_match(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, _book, (a, b, _match_id) = _finished_match_setup(
        client, db
    )
    resp = client.get(BOARD.format(code=classroom["code"]), headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    pk = data["vocabulary_pk"]
    assert pk is not None
    # 首局结算后大厅仍开放，但无排队/进行中玩家
    assert pk["open"] is True
    assert pk["queue_count"] == 0
    assert pk["active_match_count"] == 0
    assert pk["matches_this_week"] >= 1
    assert pk["last_match_at"] is not None
    last = pk["last_match"]
    assert last is not None
    assert last["winner_student_id"] == b["student"]["id"]
    assert last["winner_display_name"] == "历史乙"
    last_names = {p["display_name"] for p in last["players"]}
    assert last_names == {"历史甲", "历史乙"}
    results = {p["result"] for p in last["players"]}
    assert results == {"win", "lose"}

    # 既有看板字段口径不变
    assert data["submitted_count"] == 0
    assert data["completed_count"] == 0
    assert len(data["students"]) == 2


def test_board_pk_summary_null_when_module_disabled(
    client: TestClient, db: Session
) -> None:
    teacher, headers, classroom, _book, _ = _finished_match_setup(client, db)

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
        resp = client.get(BOARD.format(code=classroom["code"]), headers=headers)
        # 模块关闭不拦看板底座；两段词汇摘要均为 null
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["vocabulary_pk"] is None
        assert data["vocabulary_farm"] is None
    finally:
        for row in module_rows:
            row.enabled = True
        db.commit()


def test_board_non_teacher_forbidden(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, _book, (a, _b, _match_id) = _finished_match_setup(
        client, db
    )
    resp = client.get(BOARD.format(code=classroom["code"]), headers=a["headers"])
    assert resp.status_code == 403, resp.text
