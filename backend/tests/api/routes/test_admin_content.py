"""管理员内容接口测试（篇目/情景/词表导入/课堂码）。"""

from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.core.db import SCHOOL_LIFE_TOPIC, _seed_school_life_questions
from app.models import Scenario, ScenarioQuestion


@pytest.fixture
def admin(client: TestClient, superuser_token_headers: dict[str, str]) -> TestClient:
    return client  # headers 由调用方显式传


def _passages(client: TestClient, headers: dict[str, str]) -> list[dict]:
    resp = client.get("/api/v1/admin/passages", headers=headers)
    assert resp.status_code == 200
    return resp.json()


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
    mine = next(s for s in listing.json() if s["id"] == scenario["id"])
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
    scenarios = response.json()
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
    ).json()
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


def test_wordlist_import_replaces(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    csv_content = (
        "lemma,band\nfriendly,B1\nDog,A2\ncrucial,B2\nfriendly,B1\nbadrow,XX\n"
    )
    resp = client.post(
        "/api/v1/admin/wordlist/import",
        files={"file": ("wordlist.csv", csv_content.encode(), "text/csv")},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["imported"] == 3  # 重复 friendly 去重
    assert data["invalid_rows"] == [6]  # 第 6 行 band=XX 无效

    stats = client.get("/api/v1/admin/wordlist", headers=superuser_token_headers).json()
    assert stats["total"] == 3
    assert stats["by_band"] == {"A2": 1, "B1": 1, "B2": 1}

    # 恢复内置词表（后续测试依赖）
    from sqlalchemy import create_engine
    from sqlmodel import Session

    from app.core.config import settings

    engine = create_engine(str(settings.SQLALCHEMY_DATABASE_TEST_URI))
    with Session(engine) as session:
        # 先清（_seed_wordlist 幂等：只在空时写入）
        from sqlmodel import delete as sql_delete

        from app.models import WordlistEntry

        session.exec(sql_delete(WordlistEntry))  # type: ignore[call-overload]
        session.commit()
        from app.core.db import _WORDLIST_A2, _WORDLIST_B1, _WORDLIST_B2

        for band, blob in (
            ("A2", _WORDLIST_A2),
            ("B1", _WORDLIST_B1),
            ("B2", _WORDLIST_B2),
        ):
            for lemma in set(blob.split()):
                session.add(WordlistEntry(lemma=lemma, band=band))
        session.commit()
    engine.dispose()


def test_wordlist_import_rejects_bad_csv(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/v1/admin/wordlist/import",
        files={"file": ("x.csv", b"wrong,header\n1,2", "text/csv")},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


def test_classroom_admin(
    client: TestClient, superuser_token_headers: dict[str, str]
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
    # 停用后加入应 404
    join = client.post(
        f"/api/v1/classes/{created['code']}/join",
        json={"display_name": "x"},
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
        row = next(p for p in listed.json() if p["id"] == passage["id"])
        assert row["unit_id"] == unit["id"]

        # 老师端单元列表同样带篇目数（指派前完整性检查）
        classroom = client.post(
            "/api/v1/classes",
            json={"class_size": 5},
            headers=superuser_token_headers,
        ).json()
        teacher_units = client.get(
            f"/api/v1/classes/{classroom['code']}/units",
            headers=superuser_token_headers,
        ).json()
        mine2 = next(u for u in teacher_units if u["unit_id"] == unit["id"])
        assert mine2["passage_count"] == 1

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
