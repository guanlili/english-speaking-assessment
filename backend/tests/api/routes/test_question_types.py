"""三种题型体系测试：可重听次数、播放计数防刷、题型指派组卷、内容接口教师化。"""

from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import User, UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string


def _teacher(db: Session, client: TestClient) -> tuple[User, dict[str, str]]:
    email, password = random_email(), random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password, role="teacher"),
    )
    resp = client.post(
        "/api/v1/login/access-token", data={"username": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _teacher_headers_(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> dict[str, str]:
    return superuser_token_headers


# ── 可重听次数 ────────────────────────────────────────────────────────


def test_sentence_replay_limit_validation(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/v1/admin/passages",
        json={"title": "重听测试", "text": "Some text.", "topic": "Pets"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    passage = resp.json()

    ok = client.post(
        f"/api/v1/admin/passages/{passage['id']}/sentences",
        json={"order_index": 0, "text": "Listen to me.", "replay_limit": 0},
        headers=superuser_token_headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["replay_limit"] == 0  # 0=不限

    bad = client.post(
        f"/api/v1/admin/passages/{passage['id']}/sentences",
        json={"order_index": 1, "text": "Too many.", "replay_limit": 10},
        headers=superuser_token_headers,
    )
    assert bad.status_code == 422

    # 不传时默认 3
    default = client.post(
        f"/api/v1/admin/passages/{passage['id']}/sentences",
        json={"order_index": 2, "text": "Default three."},
        headers=superuser_token_headers,
    )
    assert default.json()["replay_limit"] == 3

    client.delete(
        f"/api/v1/admin/passages/{passage['id']}", headers=superuser_token_headers
    )


# ── 播放计数防刷 ─────────────────────────────────────────────────────


def test_listen_counting_blocks_overuse(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    classroom = _classroom(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"], "重听学生")
    plan = client.get(
        f"/api/v1/classes/{classroom['code']}/today",
        headers=made["headers"],
    ).json()
    repeat_item = next(i for i in plan["items"] if i["type"] == "repeat")
    assert repeat_item["replay_limit"] == 3
    assert repeat_item["listen_used"] == 0

    for i in range(1, 4):
        resp = client.post(
            f"/api/v1/classes/{classroom['code']}/listens",
            json={"session_id": plan["session_id"], "item_id": repeat_item["id"]},
            headers=made["headers"],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["listen_used"] == i

    # 第 4 次 → 422
    over = client.post(
        f"/api/v1/classes/{classroom['code']}/listens",
        json={"session_id": plan["session_id"], "item_id": repeat_item["id"]},
        headers=made["headers"],
    )
    assert over.status_code == 422

    # 计划读回已听 3 次
    plan2 = client.get(
        f"/api/v1/classes/{classroom['code']}/today",
        headers=made["headers"],
    ).json()
    item2 = next(i for i in plan2["items"] if i["id"] == repeat_item["id"])
    assert item2["listen_used"] == 3

    # 他人会话 → 404；非本人课堂句子 → 422
    other = make_student(db, client, classroom["code"], "旁听学生")
    assert (
        client.post(
            f"/api/v1/classes/{classroom['code']}/listens",
            json={"session_id": plan["session_id"], "item_id": repeat_item["id"]},
            headers=other["headers"],
        ).status_code
        == 404
    )


# ── 题型指派组卷 ─────────────────────────────────────────────────────


def test_assignment_type_gating(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    classroom = _classroom(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"], "裁剪学生")
    code = classroom["code"]

    def _today() -> dict[str, Any]:
        return client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()

    # 默认（不勾朗读）：repeat + question
    types = {i["type"] for i in _today()["items"]}
    assert types == {"repeat", "question"}

    # 纯问答轮
    resp = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"assign_repeat": False, "assign_reading": False},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    types = {i["type"] for i in _today()["items"]}
    assert types == {"question"}, f"纯问答轮应只有问答，实际 {types}"

    # 纯朗读轮
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"assign_repeat": False, "assign_qa": False, "assign_reading": True},
        headers=superuser_token_headers,
    )
    types = {i["type"] for i in _today()["items"]}
    assert types == {"passage"}, f"纯朗读轮应只有整篇朗读，实际 {types}"

    # 板块骨架同步：纯朗读轮的 board 不含复述 missing 项
    board = client.get(
        f"/api/v1/classes/{code}/board", headers=superuser_token_headers
    ).json()
    row = next(s for s in board["students"] if s["student_id"] == made["student"]["id"])
    assert {i["type"] for i in row["items"]} == {"passage"}

    # 恢复默认（全题型中朗读仍需显式）
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"assign_repeat": True, "assign_qa": True, "assign_reading": False},
        headers=superuser_token_headers,
    )
    types = {i["type"] for i in _today()["items"]}
    assert types == {"repeat", "question"}


# ── 内容接口教师化 ───────────────────────────────────────────────────


def test_teacher_can_manage_content_but_not_classrooms(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    teacher, headers = _teacher(db, client)

    # 教师可建篇目/情景/题库/单元
    passage = client.post(
        "/api/v1/admin/passages",
        json={"title": "教师出的篇目", "text": "Teacher made.", "topic": "Pets"},
        headers=headers,
    )
    assert passage.status_code == 200, passage.text

    scenario = client.post(
        "/api/v1/admin/scenarios", json={"topic": "Teacher Topic"}, headers=headers
    )
    assert scenario.status_code == 200

    unit = client.post(
        "/api/v1/admin/units",
        json={"order_index": 99, "title": "U99", "topic": "Pets"},
        headers=headers,
    )
    assert unit.status_code == 200

    # 课堂管理仍仅管理员：教师 403
    classroom = _classroom(client, superuser_token_headers)
    resp = client.put(
        f"/api/v1/admin/classrooms/{classroom['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert resp.status_code == 403

    # 学生不能碰内容
    made = make_student(db, client, classroom["code"], "好奇学生")
    resp = client.post(
        "/api/v1/admin/passages",
        json={"title": "x", "text": "y", "topic": "Pets"},
        headers=made["headers"],
    )
    assert resp.status_code == 403

    # 清理
    for path in (
        f"/api/v1/admin/passages/{passage.json()['id']}",
        f"/api/v1/admin/scenarios/{scenario.json()['id']}",
        f"/api/v1/admin/units/{unit.json()['id']}",
    ):
        client.delete(path, headers=superuser_token_headers)


def test_assigned_multi_passage_reading(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """指派组内多篇启用篇目：长文拆段后各自成为一道朗读题（按创建顺序）。"""
    classroom = _classroom(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"], "拆段学生")
    code = classroom["code"]

    units = client.get("/api/v1/admin/units", headers=superuser_token_headers).json()
    unit = next(u for u in units if u["passage_count"] >= 1)

    second = client.post(
        "/api/v1/admin/passages",
        json={
            "title": "Pets Part 2",
            "topic": "Pets",
            "cefr_band": "B1",
            "text": "Cats are also lovely. They are quiet and clean.",
            "suggested_seconds": 30,
            "unit_id": unit["id"],
        },
        headers=superuser_token_headers,
    )
    assert second.status_code == 200, second.text

    resp = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "unit_id": unit["id"],
            "assign_reading": True,
            "assign_repeat": False,
            "assign_qa": False,
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    try:
        plan = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        reading_items = [i for i in plan["items"] if i["type"] == "passage"]
        assert len(reading_items) == 2, f"应有两道朗读题，实际 {plan['items']}"
        # 按创建顺序：种子篇在前，拆出的第二段在后
        assert reading_items[0]["text"].startswith("Many students")
        assert reading_items[1]["text"].startswith("Cats are also lovely")

        # 面板同步出现两个朗读题位
        board = client.get(
            f"/api/v1/classes/{code}/board", headers=superuser_token_headers
        ).json()
        row = next(
            s for s in board["students"] if s["student_id"] == made["student"]["id"]
        )
        passage_slots = [i for i in row["items"] if i["type"] == "passage"]
        assert len(passage_slots) == 2, f"面板应有两个朗读题位，实际 {row['items']}"
    finally:
        # 清理：删除拆段篇目并解除指派，避免影响后续用例
        client.delete(
            f"/api/v1/admin/passages/{second.json()['id']}",
            headers=superuser_token_headers,
        )
        client.put(
            f"/api/v1/classes/{code}/assignment",
            json={"unit_id": None},
            headers=superuser_token_headers,
        )
