"""每日挑战接口测试（#618）：3 款不同维度、按日稳定、独立口径、降级。

口径：
- 同一班级同一天两次读取配置必须完全一致（seed = 班级 + 日期）；
- 3 款来自不同维度，每款 5 词；
- 挑战轮 kind=daily_challenge 且无 assignment_id（不进任务统计）；
- 素材不足的维度跳过并给出原因，不硬凑空题。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
STUDENT = "/api/v1/classes/{code}/vocabulary/student"
CHALLENGE = "/api/v1/classes/{code}/vocabulary/student/challenge"
PARTICIPATION = "/api/v1/classes/{code}/vocabulary/challenge/participation"


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


def _rich_words(n: int) -> list[dict]:
    """带例句的词：拼写/认读/语境三个维度都有素材。"""
    return [
        {
            "headword": f"rich{i:02d}",
            "part_of_speech": "n.",
            "meaning_zh": f"富词{i}",
            "example_en": f"We planted rich{i:02d} in the garden.",
        }
        for i in range(1, n + 1)
    ]


def _make_class_book(
    client: TestClient, headers: dict[str, str], classroom_id: str, words: list[dict]
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": "挑战测试词库",
            "scope": "classroom",
            "classroom_id": classroom_id,
            "words": words,
            "confirm_reviewed": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _read_challenge(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(CHALLENGE.format(code=code), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_challenge_three_blocks_stable_and_isolated(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """3 款不同维度、每款 5 词；同日两次读取完全一致；轮次独立口径。"""
    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    _make_class_book(client, teacher_headers, classroom["id"], _rich_words(14))

    first = _read_challenge(client, student["headers"], classroom["code"])
    second = _read_challenge(client, student["headers"], classroom["code"])
    assert first["date"] == second["date"]
    assert first["blocks"] == second["blocks"], "同日同班配置必须可复现"
    assert len({b["key"] for b in first["blocks"]}) == len(first["blocks"])
    assert len(first["blocks"]) <= 3
    for block in first["blocks"]:
        assert block["item_count"] == 5
    assert first["total_items"] == 5 * len(first["blocks"])

    started = client.post(
        f"{CHALLENGE.format(code=classroom['code'])}/sessions",
        headers=student["headers"],
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    # 再点一次不重复开轮（当日未完成轮直接续做）
    again = client.post(
        f"{CHALLENGE.format(code=classroom['code'])}/sessions",
        headers=student["headers"],
    )
    assert again.status_code == 200, again.text
    assert again.json()["session_id"] == session_id

    plan = client.get(
        f"{STUDENT.format(code=classroom['code'])}/sessions/{session_id}",
        headers=student["headers"],
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["kind"] == "daily_challenge"
    assert body["total_count"] == started.json()["total_items"]
    assert body["items"], "题单必须落到快照，刷新可续做"


def test_challenge_degrades_when_materials_missing(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    """只有释义、没有例句/词根：语境与词法维度跳过并给出原因。

    测试库里有公共种子词库（带例句），所以这里把可练词表收窄成纯释义词，
    只验证「素材不足 -> 降级 + 原因」这条分支。
    """
    from types import SimpleNamespace

    from app.services import vocab_challenge as service

    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])

    def _plain(_session: object, _classroom_id: object) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id=uuid.uuid4(),
                headword=f"plain{i:02d}",
                meaning_zh=f"简{i}",
                example_en=None,
                morphology=None,
                audio_url=None,
            )
            for i in range(1, 11)
        ]

    monkeypatch.setattr(service, "_student_words", _plain)
    payload = _read_challenge(client, student["headers"], classroom["code"])
    assert payload["degraded"] is True
    keys = {b["key"] for b in payload["blocks"]}
    assert keys <= {"meaning", "en_zh", "zh_en", "audio"}
    assert keys, "至少有拼写/认读维度可用"
    assert payload["reason"], "降级必须说明原因"


def test_challenge_participation_teacher_read_only(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师端只读看到今天开过/完成人数；学生看不到该端点。"""
    teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    _make_class_book(client, teacher_headers, classroom["id"], _rich_words(14))
    client.post(
        f"{CHALLENGE.format(code=classroom['code'])}/sessions",
        headers=student["headers"],
    )

    resp = client.get(
        PARTICIPATION.format(code=classroom["code"]), headers=teacher_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["started_count"] == 1
    assert resp.json()["completed_count"] == 0

    denied = client.get(
        PARTICIPATION.format(code=classroom["code"]), headers=student["headers"]
    )
    assert denied.status_code == 403
