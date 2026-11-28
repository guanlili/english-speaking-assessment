"""字母重排示例玩法的端到端测试（#618 收尾）：题面载荷 + 判分走通。"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
STUDENT = "/api/v1/classes/{code}/vocabulary/student"


def _teacher(db: Session, client: TestClient) -> dict[str, str]:
    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_letters_round_end_to_end(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """字母重排：字母块打乱下发、拼回原词判对、拼错判错。"""
    teacher = _teacher(db, client)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=teacher
    ).json()
    words = [
        {
            "headword": "teacher",
            "part_of_speech": "n.",
            "meaning_zh": "老师",
            "example_en": "The teacher smiled.",
        },
        {
            "headword": "garden",
            "part_of_speech": "n.",
            "meaning_zh": "花园",
            "example_en": "We walk in the garden.",
        },
        {
            "headword": "pencil",
            "part_of_speech": "n.",
            "meaning_zh": "铅笔",
            "example_en": "Pass me the pencil.",
        },
    ]
    book = client.post(
        f"{VOCAB}/books",
        json={
            "title": "字母重排测试词库",
            "scope": "classroom",
            "classroom_id": classroom["id"],
            "words": words,
            "confirm_reviewed": True,
        },
        headers=teacher,
    )
    assert book.status_code == 200, book.text
    book_id = book.json()["id"]

    student = make_student(db, client, classroom["code"])
    started = client.post(
        f"{STUDENT.format(code=classroom['code'])}/sessions",
        json={
            "kind": "self",
            "book_id": book_id,
            "word_count": 3,
            "prompt_types": ["letters"],
        },
        headers=student["headers"],
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]

    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{session_id}",
        headers=student["headers"],
    )
    assert plan.status_code == 200, plan.text
    items = plan.json()["items"]
    assert items and all(item["prompt_type"] == "letters" for item in items)
    for item in items:
        pool = item["letters_pool"]
        assert pool, "字母块必须下发"
        assert item["headword"] is None, "答题前不透露完整拼写"
        assert item["meaning_zh"], "需要中文释义作线索"

    # 用词库导出的 headword 作答：第一题答对、第二题故意拼错
    detail = client.get(f"{VOCAB}/books/{book_id}", headers=teacher).json()
    headwords = {w["meaning_zh"]: w["headword"] for w in detail["words"]}
    answers = [headwords.get(item["meaning_zh"], "") for item in items]

    first = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": 0,
            "prompt_type": "letters",
            "answer": answers[0],
        },
        headers=student["headers"],
    )
    assert first.status_code == 200, first.text
    assert first.json()["is_correct"] is True

    second = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": 1,
            "prompt_type": "letters",
            "answer": answers[1][:-1] if answers[1] else "zzz",
        },
        headers=student["headers"],
    )
    assert second.status_code == 200, second.text
    assert second.json()["is_correct"] is False
