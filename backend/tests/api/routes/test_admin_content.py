"""管理员内容接口测试（篇目/情景/词表导入/课堂码）。"""

import pytest
from fastapi.testclient import TestClient


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
        json={"topic": "School Life"},
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
    mine = next(s for s in listing.json() if s["topic"] == "School Life")
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
