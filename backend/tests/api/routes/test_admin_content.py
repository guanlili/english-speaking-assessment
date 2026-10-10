"""管理员内容接口测试（篇目/情景/词表导入/课堂码）。"""

import uuid as _uuid
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.core.db import SCHOOL_LIFE_TOPIC, _seed_school_life_questions
from app.models import Scenario, ScenarioQuestion
from tests.utils.credential import create_student_user, login_headers


@pytest.fixture
def admin(client: TestClient, superuser_token_headers: dict[str, str]) -> TestClient:
    return client  # headers 由调用方显式传


def _passages(client: TestClient, headers: dict[str, str]) -> list[dict]:
    resp = client.get("/api/v1/admin/passages", headers=headers)
    assert resp.status_code == 200
    return resp.json()["data"]


def test_list_pagination_envelope(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """四个管理列表的分页语义：limit=None 全量（组卷兼容）；skip/limit 分页 +
    count 反映过滤后总数；非法参数 422；无 token 401 不变。"""
    # scenarios：limit=None 全量 + count
    full = client.get("/api/v1/admin/scenarios", headers=superuser_token_headers)
    assert full.status_code == 200
    full_body = full.json()
    assert full_body["count"] == len(full_body["data"])
    if full_body["count"] == 0:
        return  # 空库种子不可假设，只在有数据时验证分页切片

    # limit=1 + skip 翻页：两页拼接与全量一致（稳定排序下）
    page1 = client.get(
        "/api/v1/admin/scenarios",
        params={"skip": 0, "limit": 1},
        headers=superuser_token_headers,
    ).json()
    page2 = client.get(
        "/api/v1/admin/scenarios",
        params={"skip": 1, "limit": 1},
        headers=superuser_token_headers,
    ).json()
    assert page1["count"] == full_body["count"]
    assert len(page1["data"]) == 1 and len(page2["data"]) == 1
    assert page1["data"][0]["id"] != page2["data"][0]["id"]
    assert [p["id"] for p in page1["data"] + page2["data"]] == [
        p["id"] for p in full_body["data"][:2]
    ]

    # question bank：count 跟随过滤
    bank_all = client.get(
        "/api/v1/admin/questions", headers=superuser_token_headers
    ).json()
    bank_page = client.get(
        "/api/v1/admin/questions",
        params={"skip": 0, "limit": 2},
        headers=superuser_token_headers,
    ).json()
    assert bank_page["count"] == bank_all["count"]
    assert len(bank_page["data"]) == min(2, bank_all["count"])

    # 句型库 / 篇目：同信封结构
    frames = client.get(
        "/api/v1/admin/sentence-frames", headers=superuser_token_headers
    ).json()
    assert set(frames.keys()) == {"data", "count"}
    passages = client.get(
        "/api/v1/admin/passages", headers=superuser_token_headers
    ).json()
    assert set(passages.keys()) == {"data", "count"}
    assert passages["count"] == len(passages["data"])  # limit=None 全量

    # 非法分页参数 → 422；无 token → 401（语义不变）
    assert (
        client.get(
            "/api/v1/admin/passages",
            params={"limit": 0},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/admin/passages",
            params={"skip": -1},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )


def test_admin_requires_superuser(client: TestClient) -> None:
    assert client.get("/api/v1/admin/passages").status_code == 401
    assert client.get("/api/v1/admin/scenarios").status_code == 401


def test_passage_crud_with_sentences(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # 创建
    resp = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": "test-family",
            "title": "My Family",
            "topic": "Family",
            "cefr_band": "A2",
            "text": "I have a small family.",
            "suggested_seconds": 30,
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    passage = resp.json()
    pid = passage["id"]

    # 重复 slug → 409
    dup = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": "test-family",
            "title": "dup",
            "text": "x",
        },
        headers=superuser_token_headers,
    )
    assert dup.status_code == 409

    # 加复述句
    sentence_resp = client.post(
        f"/api/v1/admin/passages/{pid}/sentences",
        json={
            "order_index": 0,
            "text": "I have a small family.",
            "suggested_seconds": 6,
        },
        headers=superuser_token_headers,
    )
    assert sentence_resp.status_code == 200
    sentence = sentence_resp.json()

    # 列表带句子
    data = _passages(client, superuser_token_headers)
    mine = next(p for p in data if p["id"] == pid)
    assert len(mine["sentences"]) == 1

    # 更新篇目
    upd = client.put(
        f"/api/v1/admin/passages/{pid}",
        json={
            "slug": "test-family",
            "title": "My Family 2",
            "topic": "Family",
            "cefr_band": "A2",
            "text": "I have a big family.",
            "suggested_seconds": 30,
        },
        headers=superuser_token_headers,
    )
    assert upd.status_code == 200
    assert upd.json()["title"] == "My Family 2"

    # 删句子、删篇目
    assert (
        client.delete(
            f"/api/v1/admin/sentences/{sentence['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/admin/passages/{pid}", headers=superuser_token_headers
        ).status_code
        == 200
    )
    assert all(p["id"] != pid for p in _passages(client, superuser_token_headers))


def test_scenario_question_crud(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/v1/admin/scenarios",
        json={"topic": "Test School Life"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    scenario = resp.json()

    # 无效档位 → 422
    bad = client.post(
        f"/api/v1/admin/scenarios/{scenario['id']}/questions",
        json={"band": "C1", "text": "?", "suggested_seconds": 30},
        headers=superuser_token_headers,
    )
    assert bad.status_code == 422

    ok = client.post(
        f"/api/v1/admin/scenarios/{scenario['id']}/questions",
        json={
            "band": "A2",
            "text": "What is your favorite subject?",
            "suggested_seconds": 20,
            "order_index": 0,
        },
        headers=superuser_token_headers,
    )
    assert ok.status_code == 200
    question = ok.json()

    listing = client.get("/api/v1/admin/scenarios", headers=superuser_token_headers)
    mine = next(s for s in listing.json()["data"] if s["id"] == scenario["id"])
    assert len(mine["questions"]) == 1

    assert (
        client.delete(
            f"/api/v1/admin/questions/{question['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/admin/scenarios/{scenario['id']}",
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_school_life_question_bank(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/admin/scenarios", headers=superuser_token_headers)
    assert response.status_code == 200
    scenarios = response.json()["data"]
    school = next(s for s in scenarios if s["topic"] == SCHOOL_LIFE_TOPIC)
    questions = school["questions"]
    assert school["is_active"] is True
    assert len(questions) == 10
    assert Counter(q["band"] for q in questions) == {"A2": 5, "B1": 5}
    assert len({q["text"] for q in questions}) == 10
    assert all(q["suggested_seconds"] == 20 for q in questions[:5])
    assert all(40 <= q["suggested_seconds"] <= 45 for q in questions[5:])
    pets = next(s for s in scenarios if s["topic"] == "Pets")
    assert Counter(q["band"] for q in pets["questions"]) == {"A2": 2, "B1": 3, "B2": 2}

    scenario = db.exec(
        select(Scenario).where(Scenario.topic == SCHOOL_LIFE_TOPIC)
    ).one()
    stored = db.exec(
        select(ScenarioQuestion)
        .where(ScenarioQuestion.scenario_id == scenario.id)
        .order_by(col(ScenarioQuestion.order_index))
    ).all()
    assert [q.order_index for q in stored] == list(range(10))
    assert [q.band for q in stored] == ["A2"] * 5 + ["B1"] * 5
    assert all(q.translation for q in stored)

    _seed_school_life_questions(db)
    _seed_school_life_questions(db)
    repeated = client.get(
        "/api/v1/admin/scenarios", headers=superuser_token_headers
    ).json()["data"]
    assert repeated == scenarios


def test_school_life_seed_preserves_teacher_changes(db: Session) -> None:
    scenario = db.exec(
        select(Scenario).where(Scenario.topic == SCHOOL_LIFE_TOPIC)
    ).one()
    question = db.exec(
        select(ScenarioQuestion).where(ScenarioQuestion.scenario_id == scenario.id)
    ).first()
    assert question is not None
    original_text = question.text
    try:
        question.text = "What do you like about your classroom?"
        scenario.is_active = False
        db.add(question)
        db.add(scenario)
        db.commit()

        _seed_school_life_questions(db)

        db.refresh(question)
        db.refresh(scenario)
        assert question.text == "What do you like about your classroom?"
        assert scenario.is_active is False
        questions = db.exec(
            select(ScenarioQuestion).where(ScenarioQuestion.scenario_id == scenario.id)
        ).all()
        assert len(questions) == 10
    finally:
        question.text = original_text
        scenario.is_active = True
        db.add(question)
        db.add(scenario)
        db.commit()


def test_classroom_admin(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    listing = client.get("/api/v1/admin/classrooms", headers=superuser_token_headers)
    assert listing.status_code == 200
    codes = [c["code"] for c in listing.json()]
    assert "DEMO01" in codes

    created = client.post(
        "/api/v1/classes", json={"class_size": 30}, headers=superuser_token_headers
    ).json()
    deactivate = client.delete(
        f"/api/v1/admin/classrooms/{created['id']}",
        headers=superuser_token_headers,
    )
    assert deactivate.status_code == 200
    # 停用后加入应 404（先过学生登录闸门：未登录会先 401）
    student_user = create_student_user(db, full_name="停用课堂")
    headers = login_headers(client, student_user.username)  # type: ignore
    join = client.post(
        f"/api/v1/classes/{created['code']}/join",
        json={"display_name": "x"},
        headers=headers,
    )
    assert join.status_code == 404


# ── Task 5：自动 slug / CEFR 档位 / 主题列表 / 单元完整性 ─────────────
# 注：测试库是会话级共享的（conftest 只在最后统一清理），本组测试创建的
# 单元/篇目/情景会在用例内显式删除，避免污染后面的关卡路径断言。


def _purge_passage(client: TestClient, headers: dict[str, str], pid: str) -> None:
    client.delete(f"/api/v1/admin/passages/{pid}", headers=headers)


def test_passage_auto_slug_is_unique(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    payload = {
        "title": "Auto Slug Passage",
        "topic": "AutoSlugTopic",
        "cefr_band": "B1",
        "text": "hello world",
    }
    created: list[str] = []
    try:
        first = client.post(
            "/api/v1/admin/passages", json=payload, headers=superuser_token_headers
        )
        assert first.status_code == 200, first.text
        created.append(first.json()["id"])
        slug = first.json()["slug"]
        assert slug

        # 同名再建不 409，而是自动加后缀
        second = client.post(
            "/api/v1/admin/passages", json=payload, headers=superuser_token_headers
        )
        assert second.status_code == 200, second.text
        created.append(second.json()["id"])
        assert second.json()["slug"] != slug
        assert second.json()["slug"].startswith(slug)

        # 显式 slug 撞名仍然 409（保留旧语义）
        dup = client.post(
            "/api/v1/admin/passages",
            json={**payload, "slug": slug},
            headers=superuser_token_headers,
        )
        assert dup.status_code == 409

        # 无 ASCII 词元的标题也能生成非空 slug
        zh = client.post(
            "/api/v1/admin/passages",
            json={**payload, "title": "我的中文标题", "slug": None},
            headers=superuser_token_headers,
        )
        assert zh.status_code == 200, zh.text
        created.append(zh.json()["id"])
        assert zh.json()["slug"]
    finally:
        for pid in created:
            _purge_passage(client, superuser_token_headers, pid)


def test_passage_cefr_band_is_enum(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    bad = client.post(
        "/api/v1/admin/passages",
        json={"title": "x", "text": "y", "cefr_band": "Z9"},
        headers=superuser_token_headers,
    )
    assert bad.status_code == 422
    assert "CEFR" in bad.json()["detail"]

    ok = client.post(
        "/api/v1/admin/passages",
        json={"title": "band-ok", "text": "y", "cefr_band": "A2"},
        headers=superuser_token_headers,
    )
    assert ok.status_code == 200, ok.text
    pid = ok.json()["id"]
    try:
        upd = client.put(
            f"/api/v1/admin/passages/{pid}",
            json={"title": "band-ok", "text": "y", "cefr_band": "C9"},
            headers=superuser_token_headers,
        )
        assert upd.status_code == 422
    finally:
        _purge_passage(client, superuser_token_headers, pid)


def test_admin_topics_are_union_and_sorted(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    passage = client.post(
        "/api/v1/admin/passages",
        json={"title": "t1", "text": "x", "topic": "主题P"},
        headers=superuser_token_headers,
    ).json()
    unit = client.post(
        "/api/v1/admin/units",
        json={"order_index": 99, "title": "u1", "topic": "主题U"},
        headers=superuser_token_headers,
    ).json()
    scenario = client.post(
        "/api/v1/admin/scenarios",
        json={"topic": "主题S", "is_active": True},
        headers=superuser_token_headers,
    ).json()
    try:
        resp = client.get("/api/v1/admin/topics", headers=superuser_token_headers)
        assert resp.status_code == 200
        topics = resp.json()
        assert {"主题P", "主题U", "主题S"} <= set(topics)
        assert topics == sorted(topics)
    finally:
        _purge_passage(client, superuser_token_headers, passage["id"])
        client.delete(
            f"/api/v1/admin/units/{unit['id']}", headers=superuser_token_headers
        )
        client.delete(
            f"/api/v1/admin/scenarios/{scenario['id']}", headers=superuser_token_headers
        )


def test_unit_passage_count_and_assignment_read_back(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    unit = client.post(
        "/api/v1/admin/units",
        json={"order_index": 98, "title": "计数单元", "topic": "CountTopic"},
        headers=superuser_token_headers,
    ).json()
    passage: dict | None = None
    classroom: dict | None = None
    try:
        assert unit["passage_count"] == 0

        passage = client.post(
            "/api/v1/admin/passages",
            json={
                "title": "counted passage",
                "text": "x",
                "topic": "CountTopic",
                "unit_id": unit["id"],
            },
            headers=superuser_token_headers,
        ).json()
        # 管理端能读回篇目所属单元
        assert passage["unit_id"] == unit["id"]

        units = client.get(
            "/api/v1/admin/units", headers=superuser_token_headers
        ).json()
        mine = next(u for u in units if u["id"] == unit["id"])
        assert mine["passage_count"] == 1

        listed = client.get("/api/v1/admin/passages", headers=superuser_token_headers)
        row = next(p for p in listed.json()["data"] if p["id"] == passage["id"])
        assert row["unit_id"] == unit["id"]

        # 停用篇目不计入（指派前检查按“学生能练到”算）
        client.put(
            f"/api/v1/admin/passages/{passage['id']}",
            json={"title": "counted passage", "text": "x", "is_active": False},
            headers=superuser_token_headers,
        )
        units = client.get(
            "/api/v1/admin/units", headers=superuser_token_headers
        ).json()
        mine = next(u for u in units if u["id"] == unit["id"])
        assert mine["passage_count"] == 0
    finally:
        if passage is not None:
            _purge_passage(client, superuser_token_headers, passage["id"])
        client.delete(
            f"/api/v1/admin/units/{unit['id']}", headers=superuser_token_headers
        )
        if classroom is not None:
            client.delete(
                f"/api/v1/admin/classrooms/{classroom['id']}",
                headers=superuser_token_headers,
            )


# ── 题库：全局列表 + 批量录入 ────────────────────────────────────────


def _mk_scenario(client: TestClient, headers: dict[str, str], topic: str) -> dict:
    resp = client.post(
        "/api/v1/admin/scenarios", json={"topic": topic}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_question_bank_requires_superuser(client: TestClient) -> None:
    assert client.get("/api/v1/admin/questions").status_code == 401


def test_question_bank_list_with_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    scenario = _mk_scenario(client, superuser_token_headers, "Test Bank Filter")
    try:
        for band, text, translation in [
            ("A2", "How do you go to school?", "你怎么去学校？"),
            ("B1", "Describe your favorite teacher.", "介绍你最喜欢的老师"),
            ("B1", "What did you do last weekend?", None),
        ]:
            resp = client.post(
                f"/api/v1/admin/scenarios/{scenario['id']}/questions",
                json={"band": band, "text": text, "translation": translation},
                headers=superuser_token_headers,
            )
            assert resp.status_code == 200, resp.text

        # 无过滤：包含本题库全部（其他主题种子也在，只验证本题都在）
        base = client.get("/api/v1/admin/questions", headers=superuser_token_headers)
        assert base.status_code == 200
        mine = [q for q in base.json()["data"] if q["topic"] == "Test Bank Filter"]
        assert len(mine) == 3
        assert all(q["scenario_id"] == scenario["id"] for q in mine)

        # 主题过滤
        by_topic = client.get(
            "/api/v1/admin/questions",
            params={"topic": "Test Bank Filter"},
            headers=superuser_token_headers,
        )
        assert len(by_topic.json()["data"]) == 3

        # 档位过滤
        by_band = client.get(
            "/api/v1/admin/questions",
            params={"topic": "Test Bank Filter", "band": "B1"},
            headers=superuser_token_headers,
        )
        assert len(by_band.json()["data"]) == 2

        # 关键词（英文）
        by_q = client.get(
            "/api/v1/admin/questions",
            params={"topic": "Test Bank Filter", "q": "weekend"},
            headers=superuser_token_headers,
        )
        assert [q["text"] for q in by_q.json()["data"]] == ["What did you do last weekend?"]

        # 关键词（中文提示）
        by_cn = client.get(
            "/api/v1/admin/questions",
            params={"topic": "Test Bank Filter", "q": "老师"},
            headers=superuser_token_headers,
        )
        assert len(by_cn.json()["data"]) == 1

        # 非法档位 → 422
        bad = client.get(
            "/api/v1/admin/questions",
            params={"band": "C1"},
            headers=superuser_token_headers,
        )
        assert bad.status_code == 422
    finally:
        _cleanup_scenario(client, superuser_token_headers, scenario["id"])


def _cleanup_scenario(
    client: TestClient, headers: dict[str, str], scenario_id: str
) -> None:
    client.delete(f"/api/v1/admin/scenarios/{scenario_id}", headers=headers)


def test_batch_create_questions_partial_success(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    scenario = _mk_scenario(client, superuser_token_headers, "Test Bank Batch")
    try:
        resp = client.post(
            f"/api/v1/admin/scenarios/{scenario['id']}/questions/batch",
            json={
                "band": "A2",
                "items": [
                    {
                        "text": "  What is your name?  ",
                        "translation": " 你叫什么名字？ ",
                    },
                    {"text": "   "},  # 空文本 → 失败
                    {"text": "How old are you?", "suggested_seconds": 5},  # 秒数越界
                    {"text": "Where do you live?"},
                ],
            },
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["created"] == 2
        assert [f["index"] for f in result["failed"]] == [1, 2]
        assert "为空" in result["failed"][0]["reason"]
        assert "10–60" in result["failed"][1]["reason"]

        rows = db.exec(
            select(ScenarioQuestion).where(
                ScenarioQuestion.scenario_id == scenario["id"]  # type: ignore[arg-type]
            )
        ).all()
        assert len(rows) == 2
        named = next(r for r in rows if r.text == "What is your name?")
        assert named.translation == "你叫什么名字？"  # 去过空白
        assert named.band == "A2"

        # 空 items → 422；非法 band → 422；不存在场景 → 404
        assert (
            client.post(
                f"/api/v1/admin/scenarios/{scenario['id']}/questions/batch",
                json={"band": "A2", "items": []},
                headers=superuser_token_headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/v1/admin/scenarios/{scenario['id']}/questions/batch",
                json={"band": "C1", "items": [{"text": "x"}]},
                headers=superuser_token_headers,
            ).status_code
            == 422
        )
        import uuid as _uuid

        assert (
            client.post(
                f"/api/v1/admin/scenarios/{_uuid.uuid4()}/questions/batch",
                json={"band": "A2", "items": [{"text": "x"}]},
                headers=superuser_token_headers,
            ).status_code
            == 404
        )
    finally:
        _cleanup_scenario(client, superuser_token_headers, scenario["id"])


def test_update_question_translation_and_bounds(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    scenario = _mk_scenario(client, superuser_token_headers, "Test Bank Edit")
    try:
        created = client.post(
            f"/api/v1/admin/scenarios/{scenario['id']}/questions",
            json={"band": "B1", "text": "Original text?"},
            headers=superuser_token_headers,
        ).json()

        updated = client.put(
            f"/api/v1/admin/questions/{created['id']}",
            json={"translation": "中文提示", "suggested_seconds": 30},
            headers=superuser_token_headers,
        )
        assert updated.status_code == 200
        # 响应模型不含 translation，用题库接口读回验证
        bank = client.get(
            "/api/v1/admin/questions",
            params={"topic": "Test Bank Edit"},
            headers=superuser_token_headers,
        ).json()["data"]
        row = next(q for q in bank if q["id"] == created["id"])
        assert row["translation"] == "中文提示"
        assert row["suggested_seconds"] == 30

        bad = client.put(
            f"/api/v1/admin/questions/{created['id']}",
            json={"suggested_seconds": 99},
            headers=superuser_token_headers,
        )
        assert bad.status_code == 422
    finally:
        _cleanup_scenario(client, superuser_token_headers, scenario["id"])


# ── 输入边界：空文本 / 负时长 / 越界序号 / 非法外键 / null 语义 ──────


def test_create_content_rejects_empty_text_and_bounds(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # 空文本（含纯空白）→ 422
    assert (
        client.post(
            "/api/v1/admin/passages",
            json={"title": "x", "text": "   ", "slug": None},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/admin/passages",
            json={"title": "   ", "text": "body", "slug": None},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/admin/sentences",
            json={"text": "   ", "order_index": 0},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/admin/scenarios",
            json={"topic": "  "},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )

    # 负序号 / 越界建议秒数 → 422
    assert (
        client.post(
            "/api/v1/admin/sentences",
            json={"text": "hi", "order_index": -1},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/admin/sentences",
            json={"text": "hi", "order_index": 0, "suggested_seconds": 2},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/admin/sentences",
            json={"text": "hi", "order_index": 0, "suggested_seconds": 61},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/admin/sentences",
            json={"text": "hi", "order_index": 0, "replay_limit": 10},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )

    # 非法外键：独立复述句挂不存在的篇目 → 404
    import uuid as _uuid

    assert (
        client.post(
            "/api/v1/admin/sentences",
            json={"text": "hi", "order_index": 0, "passage_id": str(_uuid.uuid4())},
            headers=superuser_token_headers,
        ).status_code
        == 404
    )


def test_update_content_null_and_partial_semantics(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """更新语义：缺省不修改；可空字段 null 清空；非空字段 null → 422。"""
    passage = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": "null-semantics",
            "title": "Before",
            "text": "Hello world.",
            "suggested_seconds": 30,
            "translation": "初始提示",
        },
        headers=superuser_token_headers,
    ).json()
    sentence = client.post(
        f"/api/v1/admin/passages/{passage['id']}/sentences",
        json={"order_index": 0, "text": "Repeat me.", "translation": "句提示"},
        headers=superuser_token_headers,
    ).json()
    scenario = _mk_scenario(client, superuser_token_headers, "Null 语义测试")
    question = client.post(
        f"/api/v1/admin/scenarios/{scenario['id']}/questions",
        json={"band": "A2", "text": "Q?", "translation": "问提示"},
        headers=superuser_token_headers,
    ).json()
    try:
        # 缺省不修改：只发一个字段，其它保留
        upd = client.put(
            f"/api/v1/admin/passages/{passage['id']}",
            json={"title": "After"},
            headers=superuser_token_headers,
        )
        assert upd.status_code == 200
        assert upd.json()["title"] == "After"
        assert upd.json()["text"] == "Hello world."
        assert upd.json()["suggested_seconds"] == 30

        # 可空字段 null 清空
        upd_s = client.put(
            f"/api/v1/admin/sentences/{sentence['id']}",
            json={"translation": None},
            headers=superuser_token_headers,
        )
        assert upd_s.status_code == 200
        assert upd_s.json()["translation"] is None
        assert upd_s.json()["text"] == "Repeat me."

        upd_q = client.put(
            f"/api/v1/admin/questions/{question['id']}",
            json={"translation": None},
            headers=superuser_token_headers,
        )
        assert upd_q.status_code == 200

        # 非空字段传 null → 422（suggested_seconds=null 不再落到 DB 层抛 TypeError）
        for url, payload in [
            (f"/api/v1/admin/passages/{passage['id']}", {"suggested_seconds": None}),
            (f"/api/v1/admin/passages/{passage['id']}", {"text": None}),
            (f"/api/v1/admin/sentences/{sentence['id']}", {"suggested_seconds": None}),
            (f"/api/v1/admin/sentences/{sentence['id']}", {"text": None}),
            (f"/api/v1/admin/sentences/{sentence['id']}", {"order_index": None}),
            (f"/api/v1/admin/questions/{question['id']}", {"suggested_seconds": None}),
            (f"/api/v1/admin/questions/{question['id']}", {"order_index": None}),
            (f"/api/v1/admin/questions/{question['id']}", {"band": None}),
        ]:
            resp = client.put(url, json=payload, headers=superuser_token_headers)
            assert resp.status_code == 422, (url, payload, resp.text)

        # 空白文本更新 → 422
        assert (
            client.put(
                f"/api/v1/admin/sentences/{sentence['id']}",
                json={"text": "   "},
                headers=superuser_token_headers,
            ).status_code
            == 422
        )

        # 非法外键更新：句子挂到不存在的篇目 → 422；unit_id 不存在 → 422
        assert (
            client.put(
                f"/api/v1/admin/sentences/{sentence['id']}",
                json={"passage_id": str(_uuid.uuid4())},
                headers=superuser_token_headers,
            ).status_code
            == 422
        )
        assert (
            client.put(
                f"/api/v1/admin/passages/{passage['id']}",
                json={"unit_id": str(_uuid.uuid4())},
                headers=superuser_token_headers,
            ).status_code
            == 422
        )

        # 可空外键清空合法（句子脱离篇目）
        detach = client.put(
            f"/api/v1/admin/sentences/{sentence['id']}",
            json={"passage_id": None},
            headers=superuser_token_headers,
        )
        assert detach.status_code == 200
        assert detach.json()["passage_id"] is None
    finally:
        client.delete(
            f"/api/v1/admin/questions/{question['id']}", headers=superuser_token_headers
        )
        client.delete(
            f"/api/v1/admin/scenarios/{scenario['id']}",
            headers=superuser_token_headers,
        )
        client.delete(
            f"/api/v1/admin/sentences/{sentence['id']}",
            headers=superuser_token_headers,
        )
        client.delete(
            f"/api/v1/admin/passages/{passage['id']}",
            headers=superuser_token_headers,
        )
