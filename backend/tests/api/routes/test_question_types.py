"""题型体系测试：可重听次数、播放计数防刷、题型指派组卷、题目说明（第四题型）、内容接口教师化。"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col

from app import crud
from app.models import (
    Classroom,
    ClassroomExercise,
    ScenarioQuestion,
    User,
    UserCreate,
)
from app.services import exam as exam_service
from tests.utils.audio import wav_upload
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


def test_item_assignment_independent_types(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """按题指派：三题型独立选题成卷，不经单元/篇目载体。"""
    classroom = _classroom(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"], "按题学生")
    code = classroom["code"]

    # 独立复述句：不挂篇目直接创建
    sentence = client.post(
        "/api/v1/admin/sentences",
        json={
            "order_index": 0,
            "text": "This is a standalone repeat sentence.",
            "suggested_seconds": 12,
            "replay_limit": 2,
        },
        headers=superuser_token_headers,
    )
    assert sentence.status_code == 200, sentence.text
    sentence_id = sentence.json()["id"]

    # 平铺复述句库可见（带所属篇目信息）
    flat = client.get("/api/v1/admin/sentences", headers=superuser_token_headers)
    assert flat.status_code == 200
    assert any(s["id"] == sentence_id for s in flat.json())

    # 从种子情景取一道问答题
    scenarios = client.get(
        "/api/v1/admin/scenarios", headers=superuser_token_headers
    ).json()
    scenario = next(s for s in scenarios if s["topic"] == "Pets")
    question_id = scenario["questions"][0]["id"]

    # 按题指派：1 复述 + 1 问答（无朗读、无单元）
    resp = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "items": [
                {"type": "repeat", "id": sentence_id},
                {"type": "question", "id": question_id},
            ]
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    plan = client.get(f"/api/v1/classes/{code}/today", headers=made["headers"]).json()
    assert [i["type"] for i in plan["items"]] == ["repeat", "question"]
    assert plan["items"][0]["text"] == "This is a standalone repeat sentence."
    assert plan["assigned_unit_title"] == "老师指派"

    # 面板题位同步（无会话学生按骨架展示）
    board = client.get(
        f"/api/v1/classes/{code}/board", headers=superuser_token_headers
    ).json()
    row = next(s for s in board["students"] if s["student_id"] == made["student"]["id"])
    assert {i["type"] for i in row["items"]} == {"repeat", "question"}

    # 换题：同情景其余题目（排除已指派那道）
    nxt = client.get(f"/api/v1/classes/{code}/next-question", headers=made["headers"])
    assert nxt.status_code == 200
    assert nxt.json()["question"] is not None
    assert nxt.json()["question"]["id"] != question_id

    # 非法题型引用被拒
    bad = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "essay", "id": sentence_id}]},
        headers=superuser_token_headers,
    )
    assert bad.status_code == 422

    # 清除指派回个人路径
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": []},
        headers=superuser_token_headers,
    )
    plan2 = client.get(f"/api/v1/classes/{code}/today", headers=made["headers"]).json()
    assert {i["type"] for i in plan2["items"]} == {"repeat", "question"}
    assert plan2["items"][0]["id"] != sentence_id  # 回到种子篇目的复述句


def test_split_passage_into_readings(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """长文拆句：发布后按句展开成逐句朗读题（合成 ID 指回真实篇目）。"""
    sentence_texts = [
        "I went there with my parents and my younger brother because my father thought it would be educational for us.",
        "Firstly, the building was very dark and old, and there were almost no other visitors inside.",
        "Most of the exhibits were just old dusty photographs in small glass cases.",
        "In the end, I felt it was boring because there was nothing engaging to see.",
        "I was really relieved when we finally left.",
    ]
    long_text = "\n".join(
        [
            sentence_texts[0],
            f"{sentence_texts[1]} {sentence_texts[2]}",
            f"{sentence_texts[3]} {sentence_texts[4]}",
        ]
    )
    resp = client.post(
        "/api/v1/admin/passages",
        json={
            "title": "Split Me",
            "topic": "Places",
            "cefr_band": "B1",
            "text": long_text,
            "suggested_seconds": 60,
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    original = resp.json()

    split = client.post(
        f"/api/v1/admin/passages/{original['id']}/split",
        headers=superuser_token_headers,
    )
    assert split.status_code == 200, split.text
    data = split.json()
    assert data["created"] == 5
    assert data["passage_ids"] == []
    assert data["original_deactivated"] is False

    passages = client.get(
        "/api/v1/admin/passages", headers=superuser_token_headers
    ).json()
    by_id = {p["id"]: p for p in passages}
    article = by_id[original["id"]]
    assert article["is_active"] is True
    assert article["reading_split"] is True
    assert len(article["reading_segments"]) == 5
    assert article["reading_segments"][0].endswith("educational for us.")
    assert article["sentences"] == []  # 朗读分句不混入听句复述
    repeated = client.post(
        f"/api/v1/admin/passages/{original['id']}/split",
        headers=superuser_token_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json() == data  # 重复拆句不创建额外题目

    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    student = make_student(db, client, code, "文章朗读学生")
    assigned = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "passage", "id": original["id"]}]},
        headers=superuser_token_headers,
    )
    assert assigned.status_code == 200, assigned.text
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    # 拆句展开：一篇文章 = N 道逐句朗读题
    assert [i["text"] for i in plan["items"]] == sentence_texts
    assert all(i["type"] == "passage" for i in plan["items"])
    assert all(i["parent_id"] == original["id"] for i in plan["items"])
    assert [i["sentence_index"] for i in plan["items"]] == [1, 2, 3, 4, 5]
    assert all(i["sentence_total"] == 5 for i in plan["items"])
    # 合成 ID 确定性：跨请求稳定（刷新恢复/结果页对齐依赖）
    again = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    assert [i["id"] for i in again["items"]] == [i["id"] for i in plan["items"]]

    # 逐句条目可作答：发布会话从发布快照取内容评分
    submit = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(3.0)},
        data={
            "item_type": "passage",
            "item_id": plan["items"][0]["id"],
            "duration_s": "3.0",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    )
    assert submit.status_code == 200, submit.text

    # 编辑正文会刷新分句，但已发布快照不随题库编辑变化。
    edited = "The first sentence. The second sentence!"
    update = client.put(
        f"/api/v1/admin/passages/{original['id']}",
        json={"text": edited},
        headers=superuser_token_headers,
    )
    assert update.status_code == 200, update.text
    listed = client.get(
        "/api/v1/admin/passages", headers=superuser_token_headers
    ).json()
    refreshed = next(p for p in listed if p["id"] == original["id"])
    assert refreshed["reading_segments"] == [
        "The first sentence.",
        "The second sentence!",
    ]
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    assert [i["text"] for i in plan["items"]] == sentence_texts

    # 取消拆分：再发布回到整篇一道题（已发布快照不受影响）
    unsplit = client.delete(
        f"/api/v1/admin/passages/{original['id']}/split",
        headers=superuser_token_headers,
    )
    assert unsplit.status_code == 200, unsplit.text
    assert unsplit.json()["reading_split"] is False
    republished = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "passage", "id": original["id"]}]},
        headers=superuser_token_headers,
    )
    assert republished.status_code == 200, republished.text
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    assert len(plan["items"]) == 1
    assert plan["items"][0]["id"] == original["id"]
    assert plan["items"][0]["text"] == edited

    # 只有一句时拒绝拆分（单段多句可拆）
    single = client.post(
        "/api/v1/admin/passages",
        json={
            "title": "One Para",
            "text": "Only one paragraph here.",
            "topic": "Places",
        },
        headers=superuser_token_headers,
    )
    refused = client.post(
        f"/api/v1/admin/passages/{single.json()['id']}/split",
        headers=superuser_token_headers,
    )
    assert refused.status_code == 422

    # 清理
    for pid in [*data["passage_ids"], original["id"], single.json()["id"]]:
        client.delete(f"/api/v1/admin/passages/{pid}", headers=superuser_token_headers)


def test_legacy_split_children_are_hidden_but_published_snapshots_survive(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    from app.models import Passage

    headers = superuser_token_headers
    article = client.post(
        "/api/v1/admin/passages",
        json={"title": "Legacy article", "text": "First sentence. Second sentence."},
        headers=headers,
    ).json()
    child = client.post(
        "/api/v1/admin/passages",
        json={"title": "Legacy article（一）", "text": "First sentence."},
        headers=headers,
    ).json()
    classroom = _classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "旧版分段学生")
    publish = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "passage", "id": child["id"]}]},
        headers=headers,
    )
    assert publish.status_code == 200, publish.text

    # 模拟迁移：归属与启用状态变化不触碰已发布快照。
    parent_row = db.get(Passage, uuid.UUID(article["id"]))
    child_row = db.get(Passage, uuid.UUID(child["id"]))
    assert parent_row is not None and child_row is not None
    parent_row.reading_split = True
    child_row.parent_passage_id = parent_row.id
    child_row.is_active = False
    db.add(parent_row)
    db.add(child_row)
    db.commit()
    listed = client.get("/api/v1/admin/passages", headers=headers).json()
    assert not any(p["id"] == child["id"] for p in listed)
    parent = next(p for p in listed if p["id"] == article["id"])
    assert parent["reading_child_ids"] == [child["id"]]
    assert parent["reading_segments"] == ["First sentence.", "Second sentence."]
    old_plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    assert old_plan["items"][0]["id"] == child["id"]
    assert old_plan["items"][0]["text"] == "First sentence."
    refused = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "passage", "id": child["id"]}]},
        headers=headers,
    )
    assert refused.status_code == 404
    republish = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "passage", "id": article["id"]}]},
        headers=headers,
    )
    assert republish.status_code == 200, republish.text
    plan = client.get(
        f"/api/v1/classes/{code}/today", headers=student["headers"]
    ).json()
    # 迁移后的父篇目已带 reading_split：再发布按句展开成逐句题
    assert [i["text"] for i in plan["items"]] == [
        "First sentence.",
        "Second sentence.",
    ]
    assert all(i["parent_id"] == article["id"] for i in plan["items"])
    deleted = client.delete(f"/api/v1/admin/passages/{article['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    db.expire_all()
    assert db.get(Passage, uuid.UUID(child["id"])) is None


def test_split_passage_into_sentence_readings(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """兼容 mode=sentence：句子保持顺序和标点，发布时逐句展开。"""
    sentences = ["What is your favorite food?", "I enjoy mooncakes.", "They are sweet!"]
    created = client.post(
        "/api/v1/admin/passages",
        json={"title": "Food Story", "topic": "Food", "text": " ".join(sentences)},
        headers=superuser_token_headers,
    )
    assert created.status_code == 200, created.text
    original_id = created.json()["id"]
    split = client.post(
        f"/api/v1/admin/passages/{original_id}/split?mode=sentence",
        headers=superuser_token_headers,
    )
    assert split.status_code == 200, split.text
    assert split.json()["created"] == len(sentences)
    assert split.json()["passage_ids"] == []
    passages = client.get(
        "/api/v1/admin/passages", headers=superuser_token_headers
    ).json()
    article = next(p for p in passages if p["id"] == original_id)
    assert article["reading_segments"] == sentences
    assert article["is_active"] is True
    invalid = client.post(
        f"/api/v1/admin/passages/{original_id}/split?mode=invalid",
        headers=superuser_token_headers,
    )
    assert invalid.status_code == 422
    client.delete(
        f"/api/v1/admin/passages/{original_id}", headers=superuser_token_headers
    )


def test_split_expansion_over_limit_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """拆句展开后超过单次发布 100 题上限：按展开后题数 422。"""
    text = " ".join(f"Practice sentence number {i} goes here." for i in range(101))
    created = client.post(
        "/api/v1/admin/passages",
        json={"title": "Too Long", "topic": "Places", "text": text},
        headers=superuser_token_headers,
    )
    assert created.status_code == 200, created.text
    passage_id = created.json()["id"]
    split = client.post(
        f"/api/v1/admin/passages/{passage_id}/split",
        headers=superuser_token_headers,
    )
    assert split.status_code == 200, split.text
    classroom = _classroom(client, superuser_token_headers)
    refused = client.put(
        f"/api/v1/classes/{classroom['code']}/assignment",
        json={"items": [{"type": "passage", "id": passage_id}]},
        headers=superuser_token_headers,
    )
    assert refused.status_code == 422
    assert "100" in refused.json()["detail"]
    client.delete(
        f"/api/v1/admin/passages/{passage_id}", headers=superuser_token_headers
    )


def test_explore_split_passage_sentence_fallback(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """自主练习（非发布会话）：拆句篇目逐句出题，合成 ID 提交走展开兜底。"""
    headers = superuser_token_headers
    unit = client.post(
        "/api/v1/admin/units",
        json={"order_index": 95, "title": "Explore Split", "topic": "ExploreSplit"},
        headers=headers,
    ).json()
    created = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": f"explore-split-{uuid.uuid4().hex[:8]}",
            "title": "Explore Article",
            "topic": "ExploreSplit",
            "cefr_band": "B1",
            "text": "Morning light fills the room. Birds sing outside the window.",
            "suggested_seconds": 30,
            "unit_id": unit["id"],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    passage_id = created.json()["id"]
    split = client.post(f"/api/v1/admin/passages/{passage_id}/split", headers=headers)
    assert split.status_code == 200, split.text

    classroom = _classroom(client, headers)
    code = classroom["code"]
    # 只开朗读题型勾选（不发布任何练习，会话保持非发布路径）
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"assign_reading": True},
        headers=headers,
    )
    student = make_student(db, client, code, "探索拆句学生")
    explore = client.post(
        f"/api/v1/classes/{code}/explore",
        json={"unit_id": unit["id"]},
        headers=student["headers"],
    )
    assert explore.status_code == 200, explore.text
    session_id = explore.json()["session_id"]

    plan = client.get(
        f"/api/v1/classes/{code}/today",
        params={"session_id": session_id},
        headers=student["headers"],
    ).json()
    assert [i["text"] for i in plan["items"]] == [
        "Morning light fills the room.",
        "Birds sing outside the window.",
    ]
    assert all(i["parent_id"] == passage_id for i in plan["items"])

    # 非发布会话：合成 ID 没有篇目行，提交靠拆分篇目重展开兜底
    submit = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(3.0)},
        data={
            "item_type": "passage",
            "item_id": plan["items"][1]["id"],
            "duration_s": "3.0",
            "session_id": session_id,
        },
        headers=student["headers"],
    )
    assert submit.status_code == 200, submit.text

    # 清理：取消课堂指派状态并删内容（共享库防污染）
    client.delete(f"/api/v1/admin/passages/{passage_id}", headers=headers)


def test_delete_classroom_guards(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """课堂删除：无作答可删；有作答 409 提示改停用。"""
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]

    # 空课堂直接删
    resp = client.delete(f"/api/v1/classes/{code}", headers=superuser_token_headers)
    assert resp.status_code == 200, resp.text
    listed = client.get("/api/v1/classes", headers=superuser_token_headers).json()
    assert all(c["code"] != code for c in listed)

    # 有作答的课堂拒绝删除
    classroom2 = _classroom(client, superuser_token_headers)
    code2 = classroom2["code"]
    made = make_student(db, client, code2, "作答学生")
    plan = client.get(f"/api/v1/classes/{code2}/today", headers=made["headers"]).json()
    item = next(i for i in plan["items"] if i["type"] == "repeat")
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(6.0)},
        data={
            "item_type": "repeat",
            "item_id": item["id"],
            "duration_s": "6.0",
            "session_id": plan["session_id"],
        },
        headers=made["headers"],
    )
    assert resp.status_code == 200, resp.text
    refused = client.delete(f"/api/v1/classes/{code2}", headers=superuser_token_headers)
    assert refused.status_code == 409
    assert "作答" in refused.json()["detail"]


def test_question_order_index_monotonic_after_delete(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """删除中间题后新增：order_index 取现存最大 +1，不再撞号。"""
    scenario = client.post(
        "/api/v1/admin/scenarios",
        json={"topic": "OrderTest"},
        headers=superuser_token_headers,
    )
    assert scenario.status_code == 200, scenario.text
    scenario_id = scenario.json()["id"]

    created = []
    for i in range(2):
        resp = client.post(
            f"/api/v1/admin/scenarios/{scenario_id}/questions",
            json={
                "scenario_id": scenario_id,
                "text": f"question {i}",
                "suggested_seconds": 20,
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        created.append(resp.json())
    # 此时 order_index 为 1、2（服务端从 max+1 起算）

    # 删掉最大那道，再建一道：老逻辑（数组长度）会得到重复的 2
    client.delete(
        f"/api/v1/admin/questions/{created[1]['id']}",
        headers=superuser_token_headers,
    )
    client.post(
        f"/api/v1/admin/scenarios/{scenario_id}/questions",
        json={
            "scenario_id": scenario_id,
            "text": "question after delete",
            "suggested_seconds": 20,
        },
        headers=superuser_token_headers,
    )
    # 直查库：新题 order_index = 现存最大 +1，不与剩余题撞号
    from sqlmodel import select as sql_select

    rows = db.exec(
        sql_select(ScenarioQuestion)
        .where(ScenarioQuestion.scenario_id == uuid.UUID(scenario_id))
        .order_by(col(ScenarioQuestion.order_index))
    ).all()
    orders = [q.order_index for q in rows]
    assert len(orders) == len(set(orders)), f"order_index 撞号：{orders}"
    assert orders == sorted(orders)

    client.delete(
        f"/api/v1/admin/scenarios/{scenario_id}",
        headers=superuser_token_headers,
    )


# ── 题目说明（第四种题型：无作答的纯文字引导页） ──────────────────────


def _today_plan(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(f"/api/v1/classes/{code}/today", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _cleanup_classroom(db: Session, classroom_id: str) -> None:
    row = db.get(Classroom, uuid.UUID(classroom_id))
    if row is not None:
        db.delete(row)
    db.commit()


def _make_instruction(
    client: TestClient,
    headers: dict[str, str],
    text: str = "Part B：听后复述。请先读题，点击继续后开始作答。",
    title: str | None = "Part B 开始",
    seconds: int = 15,
) -> dict:
    resp = client.post(
        "/api/v1/admin/instructions",
        json={
            "text": text,
            "suggested_seconds": seconds,
            **({"title": title} if title is not None else {}),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_instruction_crud_and_validation(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """说明库 CRUD：空文字 422、秒数范围 422、title 空串归 null、删除后 404。"""
    blank = client.post(
        "/api/v1/admin/instructions",
        json={"text": "   "},
        headers=superuser_token_headers,
    )
    assert blank.status_code == 422
    bad_seconds = client.post(
        "/api/v1/admin/instructions",
        json={"text": "ok", "suggested_seconds": 301},
        headers=superuser_token_headers,
    )
    assert bad_seconds.status_code == 422

    created = _make_instruction(client, superuser_token_headers)
    assert created["title"] == "Part B 开始"
    assert created["suggested_seconds"] == 15

    listed = client.get("/api/v1/admin/instructions", headers=superuser_token_headers)
    assert listed.status_code == 200
    assert any(i["id"] == created["id"] for i in listed.json())

    # title 空串归 null；text 显式 null 422
    updated = client.put(
        f"/api/v1/admin/instructions/{created['id']}",
        json={"title": "   "},
        headers=superuser_token_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] is None
    null_text = client.put(
        f"/api/v1/admin/instructions/{created['id']}",
        json={"text": None},
        headers=superuser_token_headers,
    )
    assert null_text.status_code == 422

    deleted = client.delete(
        f"/api/v1/admin/instructions/{created['id']}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
    missing = client.get(
        "/api/v1/admin/instructions", headers=superuser_token_headers
    ).json()
    assert all(i["id"] != created["id"] for i in missing)


def test_instruction_assignment_ack_and_board(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """说明穿插进卷：today 顺序与内容、ack 幂等、面板已读、attempts 拒收说明。"""
    classroom = _classroom(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"], "说明学生")
    code = classroom["code"]

    instruction = _make_instruction(client, superuser_token_headers)
    sentence = client.post(
        "/api/v1/admin/sentences",
        json={"order_index": 0, "text": "Repeat after me.", "replay_limit": 1},
        headers=superuser_token_headers,
    )
    assert sentence.status_code == 200, sentence.text

    resp = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "items": [
                {"type": "instruction", "id": instruction["id"]},
                {"type": "repeat", "id": sentence.json()["id"]},
            ]
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    plan = client.get(f"/api/v1/classes/{code}/today", headers=made["headers"]).json()
    assert [i["type"] for i in plan["items"]] == ["instruction", "repeat"]
    ins_item = plan["items"][0]
    assert ins_item["title"] == "Part B 开始"
    assert "Part B" in ins_item["text"]
    assert ins_item["suggested_seconds"] == 15
    assert ins_item["acked_at"] is None

    # 说明不允许走音频作答
    bad_attempt = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(3.0)},
        data={
            "item_type": "instruction",
            "item_id": instruction["id"],
            "duration_s": "3.0",
            "session_id": plan["session_id"],
        },
        headers=made["headers"],
    )
    assert bad_attempt.status_code == 422

    # 面板：说明题位未读 missing，且不占 total_count
    board = client.get(
        f"/api/v1/classes/{code}/board", headers=superuser_token_headers
    ).json()
    row = next(s for s in board["students"] if s["student_id"] == made["student"]["id"])
    ins_board = next(i for i in row["items"] if i["type"] == "instruction")
    assert ins_board["status"] == "missing"
    assert row["total_count"] == 1

    # 点「继续」：ack 落库且幂等（时间戳不变）
    ack = client.post(
        f"/api/v1/classes/{code}/acks",
        json={"session_id": plan["session_id"], "item_id": instruction["id"]},
        headers=made["headers"],
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["acked"] is True
    acked_at = ack.json()["acked_at"]
    again = client.post(
        f"/api/v1/classes/{code}/acks",
        json={"session_id": plan["session_id"], "item_id": instruction["id"]},
        headers=made["headers"],
    )
    assert again.status_code == 200
    assert again.json()["acked_at"] == acked_at

    refreshed = client.get(
        f"/api/v1/classes/{code}/today", headers=made["headers"]
    ).json()
    assert refreshed["items"][0]["acked_at"] == acked_at

    # 面板已读
    board2 = client.get(
        f"/api/v1/classes/{code}/board", headers=superuser_token_headers
    ).json()
    row2 = next(
        s for s in board2["students"] if s["student_id"] == made["student"]["id"]
    )
    ins_board2 = next(i for i in row2["items"] if i["type"] == "instruction")
    assert ins_board2["status"] == "done"

    # 不在快照里的说明 ack 被拒
    stranger = _make_instruction(client, superuser_token_headers, text="别的说明")
    stranger_ack = client.post(
        f"/api/v1/classes/{code}/acks",
        json={"session_id": plan["session_id"], "item_id": stranger["id"]},
        headers=made["headers"],
    )
    assert stranger_ack.status_code == 422


def test_instruction_only_or_missing_rejected(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """只有说明不能成卷；不存在的说明 404。"""
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    instruction = _make_instruction(client, superuser_token_headers)

    only = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={"items": [{"type": "instruction", "id": instruction["id"]}]},
        headers=superuser_token_headers,
    )
    assert only.status_code == 422
    assert "可作答" in only.json()["detail"]

    sentence = client.post(
        "/api/v1/admin/sentences",
        json={"order_index": 0, "text": "Existence check sentence.", "replay_limit": 1},
        headers=superuser_token_headers,
    )
    assert sentence.status_code == 200, sentence.text
    missing = client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "items": [
                {"type": "instruction", "id": str(uuid.uuid4())},
                {"type": "repeat", "id": sentence.json()["id"]},
            ]
        },
        headers=superuser_token_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "题目说明不存在"


def test_instruction_excluded_from_settlement(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """说明不进结算分母：卷内唯一可作答题答完即结算星/XP。"""
    classroom = _classroom(client, superuser_token_headers)
    made = make_student(db, client, classroom["code"], "结算学生")
    code = classroom["code"]

    instruction = _make_instruction(client, superuser_token_headers)
    sentence = client.post(
        "/api/v1/admin/sentences",
        json={"order_index": 0, "text": "Settlement sentence.", "replay_limit": 1},
        headers=superuser_token_headers,
    )
    assert sentence.status_code == 200, sentence.text
    client.put(
        f"/api/v1/classes/{code}/assignment",
        json={
            "items": [
                {"type": "repeat", "id": sentence.json()["id"]},
                {"type": "instruction", "id": instruction["id"]},
            ]
        },
        headers=superuser_token_headers,
    )
    plan = client.get(f"/api/v1/classes/{code}/today", headers=made["headers"]).json()
    assert plan["gamification"]["session_stars"] is None

    repeat_item = next(i for i in plan["items"] if i["type"] == "repeat")
    attempt = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(4.0)},
        data={
            "item_type": "repeat",
            "item_id": repeat_item["id"],
            "duration_s": "4.0",
            "session_id": plan["session_id"],
        },
        headers=made["headers"],
    )
    assert attempt.status_code == 200, attempt.text

    # mock 评分异步：轮询到终态后 today 应已结算（说明未 ack 不阻塞）
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        plan = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        if plan["gamification"]["session_stars"] is not None:
            break
        time.sleep(0.2)
    assert plan["gamification"]["session_stars"] is not None


def test_exam_instruction_window(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模考：说明占计时窗（未开考/提前 ack 后面的说明被拒，到时自动翻页）。"""
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    made = make_student(db, client, code, "模考说明生")
    headers = made["headers"]

    ids = [uuid.uuid4() for _ in range(2)]
    snapshot: list[dict[str, object]] = [
        {
            "type": "instruction",
            "id": str(ids[0]),
            "title": "开考说明",
            "text": "Read the instructions carefully.",
            "suggested_seconds": 15,
        },
        {
            "type": "question",
            "id": str(ids[1]),
            "text": "Describe your room.",
            "suggested_seconds": 20,
        },
    ]
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        snapshot_items=snapshot,
        is_exam=True,
        time_limit_minutes=30,
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()

    now = datetime.now(UTC)
    monkeypatch.setattr(exam_service, "_now", lambda: now)
    try:
        plan = _today_plan(client, headers, code)
        assert plan["exam"]["started"] is False

        # 未开考：ack 被拒
        pre = client.post(
            f"/api/v1/classes/{code}/acks",
            json={"session_id": plan["session_id"], "item_id": str(ids[0])},
            headers=headers,
        )
        assert pre.status_code == 422

        start = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert start.status_code == 200
        assert start.json()["current_item_index"] == 0

        # 说明窗内 ack 第二道题？说明只认 instruction 条目，先确认后面的题不能 ack
        future_q = client.post(
            f"/api/v1/classes/{code}/acks",
            json={"session_id": plan["session_id"], "item_id": str(ids[1])},
            headers=headers,
        )
        assert future_q.status_code == 422

        # 提前确认（点继续）→ 题窗推进到问答题
        ack = client.post(
            f"/api/v1/classes/{code}/acks",
            json={"session_id": plan["session_id"], "item_id": str(ids[0])},
            headers=headers,
        )
        assert ack.status_code == 200, ack.text
        refreshed = _today_plan(client, headers, code)
        assert refreshed["exam"]["current_item_index"] == 1
        ins_item = next(i for i in refreshed["items"] if i["type"] == "instruction")
        assert ins_item["acked_at"] is not None

        # 已确认过的说明再 ack（幂等）仍然 200
        again = client.post(
            f"/api/v1/classes/{code}/acks",
            json={"session_id": plan["session_id"], "item_id": str(ids[0])},
            headers=headers,
        )
        assert again.status_code == 200

        # 不 ack 问答题、到时自动推进并惰性交卷
        now += timedelta(seconds=25)
        finished = _today_plan(client, headers, code)
        assert finished["exam"]["current_item_index"] == 2
        assert finished["exam"]["ended"] is True
    finally:
        _cleanup_classroom(db, classroom["id"])
