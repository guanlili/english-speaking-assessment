"""AI 出题与自动拆句（P3）：生成草稿解析、503 降级、拆句幂等、Scenario PUT。"""

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.scoring.ark_client import (
    ArkChatClient,
    ArkChatError,
    parse_json_list,
    parse_json_payload,
)
from app.scoring.question_gen import (
    build_generation_user_prompt,
    generate_draft_questions,
)

# ── ark_client 容错解析 ──────────────────────────────────────────────


def test_parse_json_list_strips_fences() -> None:
    content = '```json\n[{"text": "q?", "suggested_seconds": 30}]\n```'
    items = parse_json_list(content)
    assert items[0]["text"] == "q?"


def test_parse_json_list_rejects_plain_text() -> None:
    with pytest.raises(ValueError, match="JSON"):
        parse_json_list("no array here")


def test_parse_json_payload_roundtrip() -> None:
    assert parse_json_payload('{"a": 1}') == {"a": 1}


def test_chat_client_requires_key() -> None:
    with pytest.raises(ArkChatError, match="ARK_API_KEY"):
        ArkChatClient(api_key=None, model="m").chat("s", "u")


# ── question_gen ─────────────────────────────────────────────────────


def test_generation_prompt_contains_band_specs() -> None:
    prompt = build_generation_user_prompt("Pets", "B1", 3, "贴近生活")
    assert (
        "Pets" in prompt and "B1" in prompt and "3" in prompt and "贴近生活" in prompt
    )


def test_generate_draft_questions_via_mock_chat(monkeypatch) -> None:
    class FakeChat(ArkChatClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(
                api_key="key",
                model="m",
                **{k: v for k, v in kwargs.items() if k in ("base_url", "client")},
            )

        def chat(
            self,
            system: str,
            user: str,
            model: str | None = None,
            temperature: float = 0.2,
        ) -> str:
            assert "exactly 2" in user
            return json.dumps(
                [
                    {"text": "Do you like cats?", "suggested_seconds": 15},
                    {"text": "Why do people keep pets?", "suggested_seconds": 30},
                ]
            )

    import app.scoring.question_gen as qg

    monkeypatch.setattr(qg, "ArkChatClient", FakeChat)
    drafts = generate_draft_questions("Pets", "A2", 2)
    assert [d.text for d in drafts] == [
        "Do you like cats?",
        "Why do people keep pets?",
    ]
    assert drafts[0].suggested_seconds == 15


def test_generate_rejects_bad_band() -> None:
    with pytest.raises(ValueError, match="A2/B1/B2"):
        generate_draft_questions("Pets", "C1", 3)


# ── admin 端点 ───────────────────────────────────────────────────────


def _scenario(client: TestClient, headers: dict) -> Any:
    resp = client.post(
        "/api/v1/admin/scenarios",
        json={"topic": f"AI出题{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()


def test_generate_endpoint_503_without_key(
    client: TestClient, superuser_token_headers: dict, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "ARK_API_KEY", None)
    scenario = _scenario(client, superuser_token_headers)
    resp = client.post(
        f"/api/v1/admin/scenarios/{scenario['id']}/questions/generate",
        json={"band": "B1", "count": 3},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 503
    assert "暂不可用" in resp.json()["detail"]


def test_generate_endpoint_drafts_not_saved(
    client: TestClient, superuser_token_headers: dict, monkeypatch
) -> None:
    """AI 生成只出草稿，不入库（PRD 红线）。"""
    import app.scoring.question_gen as qg

    class FakeChat(ArkChatClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(
                api_key="key",
                model="m",
                **{k: v for k, v in kwargs.items() if k in ("base_url", "client")},
            )

        def chat(
            self,
            system: str,
            user: str,
            model: str | None = None,
            temperature: float = 0.2,
        ) -> str:
            return '[{"text": "Q1?", "suggested_seconds": 20}]'

    monkeypatch.setattr(settings, "ARK_API_KEY", "fake")
    monkeypatch.setattr(qg, "ArkChatClient", FakeChat)

    scenario = _scenario(client, superuser_token_headers)
    resp = client.post(
        f"/api/v1/admin/scenarios/{scenario['id']}/questions/generate",
        json={"band": "B1", "count": 1},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    drafts = resp.json()
    assert len(drafts) == 1 and drafts[0]["text"] == "Q1?"

    listing = client.get(
        "/api/v1/admin/scenarios", headers=superuser_token_headers
    ).json()
    mine = next(s for s in listing if s["id"] == scenario["id"])
    assert mine["questions"] == []  # 未入库


def test_scenario_update(client: TestClient, superuser_token_headers: dict) -> None:
    scenario = _scenario(client, superuser_token_headers)
    upd = client.put(
        f"/api/v1/admin/scenarios/{scenario['id']}",
        json={"topic": f"改名{uuid.uuid4().hex[:6]}"},
        headers=superuser_token_headers,
    )
    assert upd.status_code == 200
    assert upd.json()["topic"].startswith("改名")


def test_auto_split_creates_and_is_guarded(
    client: TestClient, superuser_token_headers: dict
) -> None:
    """自动拆句：建句 → 再拆被拒（幂等护栏）。"""
    created = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": f"split-{uuid.uuid4().hex[:6]}",
            "title": "拆句测试",
            "topic": "Pets",
            "cefr_band": "A2",
            "text": "Cats sleep a lot. I have two cats at home. "
            "They like to sit near the window in the morning sun. "
            "Dogs need walks every day.",
            "suggested_seconds": 30,
        },
        headers=superuser_token_headers,
    ).json()

    resp = client.post(
        f"/api/v1/admin/passages/{created['id']}/sentences/auto-split",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 3
    # 由短到长选出的 3 句可在篇目详情里按原顺序验证
    detail = client.get(
        "/api/v1/admin/passages", headers=superuser_token_headers
    ).json()
    mine = next(p2 for p2 in detail if p2["id"] == created["id"])
    texts = [s2["text"] for s2 in mine["sentences"]]
    assert texts == [
        "Cats sleep a lot",
        "I have two cats at home",
        "Dogs need walks every day",
    ]

    # 已有句子 → 409
    again = client.post(
        f"/api/v1/admin/passages/{created['id']}/sentences/auto-split",
        headers=superuser_token_headers,
    )
    assert again.status_code == 409


def test_auto_split_needs_enough_sentences(
    client: TestClient, superuser_token_headers: dict
) -> None:
    created = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": f"short-{uuid.uuid4().hex[:6]}",
            "title": "太短",
            "topic": "Pets",
            "cefr_band": "A2",
            "text": "Only one sentence here.",
            "suggested_seconds": 20,
        },
        headers=superuser_token_headers,
    ).json()
    resp = client.post(
        f"/api/v1/admin/passages/{created['id']}/sentences/auto-split",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422
