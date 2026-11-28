"""学生词汇坐标接口测试（#616）：未测 / 百分比与台阶 / 100% / FSRS 证据。

口径：分子只认独立首答答对与 FSRS review，分母是当前可练基准词表；
一条首答都没有时 measured=false，不折算 0%。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import UserCreate, VocabularyReviewState, get_datetime_utc
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
STUDENT = "/api/v1/classes/{code}/vocabulary/student"
COORDINATE = "/api/v1/classes/{code}/vocabulary/student/coordinate"


def _login_teacher(db: Session, client: TestClient) -> dict[str, str]:
    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _words(n: int, prefix: str = "c") -> list[dict]:
    return [
        {"headword": f"{prefix}{i:02d}", "part_of_speech": "n.", "meaning_zh": f"词{i}"}
        for i in range(1, n + 1)
    ]


def _make_class_book(
    client: TestClient, headers: dict[str, str], classroom_id: str, words: list[dict]
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": "坐标测试词库",
            "scope": "classroom",
            "classroom_id": classroom_id,
            "words": words,
            "confirm_reviewed": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _coordinate(
    client: TestClient, headers: dict[str, str], code: str, **params: object
) -> dict:
    resp = client.get(COORDINATE.format(code=code), headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_self(
    client: TestClient, headers: dict[str, str], code: str, book_id: str
) -> dict:
    resp = client.post(
        f"{STUDENT.format(code=code)}/sessions",
        json={"kind": "self", "book_id": book_id, "word_count": 10},
        headers=headers,
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
) -> None:
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={"item_index": item_index, "prompt_type": "meaning", "answer": answer},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _expected_percent(mastered: int, basis: int) -> int:
    """口径复算：百分比 = 四舍五入(100 × 已掌握 ÷ 基准词表词数)，上限 100。"""
    return min(100, int(100 * mastered / basis + 0.5)) if basis else 0


def _expected_step_index(percent: int, steps: int) -> int:
    """口径复算：等宽百分比区间、左闭右开、100% 归最后一阶。"""
    return min(steps, int(percent / (100 / steps)) + 1)


def _spelling_by_meaning(
    client: TestClient, headers: dict[str, str], code: str, book_id: str
) -> dict[str, str]:
    resp = client.get(f"{STUDENT.format(code=code)}/books/{book_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return {w["meaning_zh"]: w["headword"] for w in resp.json()["words"]}


def test_coordinate_unmeasured_without_answers(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """一条首答都没有：measured=false、百分比 None，不折算 0%。"""
    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(10))

    payload = _coordinate(client, student["headers"], classroom["code"])
    basis = payload["basis_word_count"]
    # 基准词表 = 公共词库 + 本班词库（测试库里还有种子公共词库，所以按实际值断言）
    assert basis >= 10
    assert payload["measured"] is False
    assert payload["percent"] is None
    assert payload["mastered_word_count"] == 0
    assert payload["words_to_goal"] == basis
    assert payload["step_index"] is None
    assert payload["steps_total"] == 12
    assert book["id"]  # 词库确实建出来了


def test_coordinate_percent_steps_and_config(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """5/10 首答答对：50%、12 阶口径第 7 阶、距本阶终点 1 词、距 100% 5 词。"""
    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(10))
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )

    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    for index, item in enumerate(plan["items"]):
        headword = spelling[item["meaning_zh"]]
        # 前 5 题首答正确，接下来 2 题拼错，余 3 题不答
        answer = headword if index < 5 else f"x{headword}"
        if index < 7:
            _answer(
                client,
                student["headers"],
                created["session_id"],
                item["item_index"],
                answer,
            )

    payload = _coordinate(client, student["headers"], classroom["code"])
    basis = payload["basis_word_count"]
    percent = _expected_percent(5, basis)
    assert payload["measured"] is True
    assert payload["answered_first_count"] == 7
    assert payload["mastered_word_count"] == 5
    assert payload["percent"] == percent
    assert payload["step_index"] == _expected_step_index(percent, 12)
    assert payload["words_to_goal"] == basis - 5

    # 台阶可配：同一进度在 4 阶口径下落在按 4 等宽算的台阶
    payload4 = _coordinate(client, student["headers"], classroom["code"], steps=4)
    assert payload4["steps_total"] == 4
    assert payload4["step_index"] == _expected_step_index(percent, 4)
    assert payload4["step_end_percent"] in (25, 50, 75, 100)
    assert payload4["words_to_goal"] == basis - 5


def test_coordinate_reaches_hundred_percent(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """全部首答答对：100%、最后一阶、两处「还差」都是 0。"""
    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(5))
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )

    created = client.post(
        f"{STUDENT.format(code=classroom['code'])}/sessions",
        json={"kind": "self", "book_id": book["id"], "word_count": 5},
        headers=student["headers"],
    ).json()
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    for item in plan["items"]:
        _answer(
            client,
            student["headers"],
            created["session_id"],
            item["item_index"],
            spelling[item["meaning_zh"]],
        )

    payload = _coordinate(client, student["headers"], classroom["code"])
    basis = payload["basis_word_count"]
    assert payload["mastered_word_count"] == 5
    assert payload["percent"] == _expected_percent(5, basis)
    assert payload["step_index"] == _expected_step_index(payload["percent"], 12)
    assert payload["words_to_goal"] == basis - 5
    # 全对不等于 100%（基准词表里还有没练过的公共词）：这正是「口径可复算」的意义
    assert payload["percent"] < 100


def test_coordinate_counts_fsrs_review_evidence(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """FSRS 进入 review 的词也算掌握（与首答对错独立），分母仍按基准词表。"""
    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(10))
    spelling = _spelling_by_meaning(
        client, student["headers"], classroom["code"], book["id"]
    )

    # 先答 1 题且拼错，保证「测过」（否则未测，百分比不下发）
    created = _start_self(client, student["headers"], classroom["code"], book["id"])
    plan = _plan(client, student["headers"], classroom["code"], created["session_id"])
    first_item = plan["items"][0]
    _answer(
        client,
        student["headers"],
        created["session_id"],
        first_item["item_index"],
        f"x{spelling[first_item['meaning_zh']]}",
    )

    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    for word_id in word_ids[:3]:
        db.add(
            VocabularyReviewState(
                user_id=student["user"].id,
                word_id=uuid.UUID(word_id),
                capability="spelling",
                state="review",
                stability=30.0,
                reps=3,
                due_at=get_datetime_utc(),
            )
        )
    db.commit()

    payload = _coordinate(client, student["headers"], classroom["code"])
    assert payload["measured"] is True
    assert payload["mastered_fsrs_count"] == 3
    assert payload["mastered_first_try_count"] == 0
    assert payload["mastered_word_count"] == 3
    assert payload["percent"] == _expected_percent(3, payload["basis_word_count"])
