"""课堂大屏 PK「房间码」闭环测试：开房、凭码入场、服务端时钟、团队计分、
幂等与口径隔离。

口径：作答只落 vocab_pk_room_answer，不产生 VocabularyAnswer；跨班凭码 404。
"""

import time
import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import VocabPkRoom, VocabPkRoomAnswer, VocabularyAnswer
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

ROOM = "/api/v1/classes/{code}/vocabulary/room"


def _login_teacher(db: Session, client: TestClient):
    from app import crud
    from app.models import UserCreate

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
    resp = client.post("/api/v1/classes", json={"class_size": 40}, headers=headers)
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


def _create_room(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    book_id: str,
    *,
    question_count: int = 4,
    per_question_seconds: int = 20,
    mode: str = "solo",
    team_count: int | None = None,
) -> dict:
    body: dict = {
        "book_id": book_id,
        "question_count": question_count,
        "per_question_seconds": per_question_seconds,
        "prompt_types": ["meaning"],
        "mode": mode,
    }
    if team_count is not None:
        body["team_count"] = team_count
    resp = client.post(ROOM.format(code=code), json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start(client: TestClient, headers: dict[str, str], code: str, room: dict) -> dict:
    resp = client.post(
        f"{ROOM.format(code=code)}/{room['room_id']}/start", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(
    client: TestClient, headers: dict[str, str], code: str, room_code: str
) -> dict:
    resp = client.post(
        f"{ROOM.format(code=code)}/join", json={"code": room_code}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _me(client: TestClient, headers: dict[str, str], code: str, room: dict) -> dict:
    resp = client.get(f"{ROOM.format(code=code)}/{room['room_id']}/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _answer(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    room: dict,
    item_index: int,
    answer: str,
):
    resp = client.post(
        f"{ROOM.format(code=code)}/{room['room_id']}/answers",
        json={"item_index": item_index, "prompt_type": "meaning", "answer": answer},
        headers=headers,
    )
    return resp.json() | {"_status": resp.status_code}


def _spelling_map(client: TestClient, headers: dict[str, str], book_id: str) -> dict:
    resp = client.get(f"/api/v1/vocabulary/books/{book_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return {w["meaning_zh"]: w["headword"] for w in resp.json()["words"]}


def test_student_cannot_create_room(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "a"), "a1")
    student = make_student(db, client, classroom["code"])

    resp = client.post(
        ROOM.format(code=classroom["code"]),
        json={"book_id": book["id"], "question_count": 4},
        headers=student["headers"],
    )
    assert resp.status_code == 403, resp.text


def test_room_code_and_join_waiting(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "b"), "b1")
    room = _create_room(
        client, teacher_headers, classroom["code"], book["id"], question_count=3
    )

    assert len(room["room_code"]) == 6 and room["room_code"].isdigit()
    assert room["status"] == "waiting"

    student = make_student(db, client, classroom["code"])
    view = _join(client, student["headers"], classroom["code"], room["room_code"])
    assert view["status"] == "waiting"
    assert view["item"] is None
    assert view["me"]["student_id"] == student["student"]["id"]
    assert view["participants"] == 1


def test_wrong_code_and_cross_class_join_404(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    other_teacher, other_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    other_classroom = _create_classroom(client, other_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "c"), "c1")
    room = _create_room(
        client, teacher_headers, classroom["code"], book["id"], question_count=3
    )

    student = make_student(db, client, classroom["code"])
    resp = client.post(
        f"{ROOM.format(code=classroom['code'])}/join",
        json={"code": "000000" if room["room_code"] != "000000" else "111111"},
        headers=student["headers"],
    )
    assert resp.status_code == 404, resp.text

    outsider = make_student(db, client, other_classroom["code"])
    resp = client.post(
        f"{ROOM.format(code=other_classroom['code'])}/join",
        json={"code": room["room_code"]},
        headers=outsider["headers"],
    )
    assert resp.status_code == 404, resp.text


def test_answer_flow_idempotency_and_isolation(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(6, "d"), "d1")
    room = _create_room(
        client, teacher_headers, classroom["code"], book["id"], question_count=3
    )
    student = make_student(db, client, classroom["code"])
    _join(client, student["headers"], classroom["code"], room["room_code"])
    started = _start(client, teacher_headers, classroom["code"], room)
    assert started["status"] == "live"

    view = _me(client, student["headers"], classroom["code"], room)
    assert view["item"]["item_index"] == 0
    assert view["item"]["headword"] is None  # 未答不泄题
    spells = _spelling_map(client, teacher_headers, book["id"])
    word = spells[view["item"]["meaning_zh"]]

    # 翻页后旧题提交被拒（先验证错误题序）
    bad = _answer(client, student["headers"], classroom["code"], room, 1, word)
    assert bad["_status"] == 409

    first = _answer(client, student["headers"], classroom["code"], room, 0, word)
    assert first["_status"] == 200, first
    assert first["is_correct"] is True
    assert first["score"] >= 100
    assert first["headword"] == word
    assert first["my_score"] == first["score"]

    replay = _answer(client, student["headers"], classroom["code"], room, 0, word)
    assert replay["_status"] == 200
    assert replay["score"] == first["score"]  # 不二次计分

    after = _me(client, student["headers"], classroom["code"], room)
    assert after["me"]["score"] == first["score"]
    assert after["me"]["answered_count"] == 1
    assert after["item"]["headword"] == word

    # 口径隔离：房间作答不写任务作答
    answers = db.exec(
        select(VocabPkRoomAnswer).where(
            VocabPkRoomAnswer.room_id == uuid.UUID(room["room_id"])
        )
    ).all()
    assert len(answers) == 1
    task_answers = db.exec(select(VocabularyAnswer)).all()
    assert task_answers == []


def test_team_mode_auto_split_and_team_scores(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(4, "e"), "e1")
    room = _create_room(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        mode="team",
        team_count=2,
    )
    assert room["mode"] == "team" and room["team_count"] == 2

    students = [
        make_student(db, client, classroom["code"], name=f"学生{i}") for i in range(4)
    ]
    for student in students:
        _join(client, student["headers"], classroom["code"], room["room_code"])

    board = client.get(
        f"{ROOM.format(code=classroom['code'])}/{room['room_id']}/board",
        headers=teacher_headers,
    )
    assert board.status_code == 200, board.text
    data = board.json()
    assert data["participant_count"] == 4
    assert [t["member_count"] for t in data["teams"]] == [2, 2]
    assert [t["label"] for t in data["teams"]] == ["第 1 组", "第 2 组"]


def test_clock_advances_and_late_answer_rejected(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(3, "f"), "f1")
    room = _create_room(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=3,
        per_question_seconds=1,
    )
    student = make_student(db, client, classroom["code"])
    _join(client, student["headers"], classroom["code"], room["room_code"])
    _start(client, teacher_headers, classroom["code"], room)

    time.sleep(1.3)
    view = _me(client, student["headers"], classroom["code"], room)
    assert view["current_item_index"] >= 1
    late = _answer(client, student["headers"], classroom["code"], room, 0, "f01")
    assert late["_status"] == 409


def test_host_board_reveals_only_past_questions(
    client: TestClient, db: Session
) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(3, "g"), "g1")
    room = _create_room(
        client,
        teacher_headers,
        classroom["code"],
        book["id"],
        question_count=3,
        per_question_seconds=1,
    )
    student = make_student(db, client, classroom["code"])
    _join(client, student["headers"], classroom["code"], room["room_code"])
    _start(client, teacher_headers, classroom["code"], room)

    board = client.get(
        f"{ROOM.format(code=classroom['code'])}/{room['room_id']}/board",
        headers=teacher_headers,
    ).json()
    assert board["current_item"]["headword"] is None
    assert board["questions"][0]["headword"] is None

    time.sleep(1.3)
    board2 = client.get(
        f"{ROOM.format(code=classroom['code'])}/{room['room_id']}/board",
        headers=teacher_headers,
    ).json()
    assert board2["questions"][0]["headword"] is not None
    assert board2["questions"][1]["headword"] is None


def test_room_persists_until_ended(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    book = _make_book(client, teacher_headers, classroom["id"], _words(3, "h"), "h1")
    room = _create_room(
        client, teacher_headers, classroom["code"], book["id"], question_count=3
    )

    current = client.get(
        f"{ROOM.format(code=classroom['code'])}/current", headers=teacher_headers
    )
    assert current.status_code == 200, current.text
    assert current.json()["room_code"] == room["room_code"]

    ended = client.post(
        f"{ROOM.format(code=classroom['code'])}/{room['room_id']}/end",
        headers=teacher_headers,
    ).json()
    assert ended["status"] == "ended"
    assert ended["result"]["questions"]

    stored = db.exec(
        select(VocabPkRoom).where(VocabPkRoom.id == uuid.UUID(room["room_id"]))
    ).first()
    assert stored is not None and stored.status == "ended"
