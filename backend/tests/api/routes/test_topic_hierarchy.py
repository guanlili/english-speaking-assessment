"""题库三层收敛（主题→篇目→句子）的行为约束。

主题单一事实源：挂单元的篇目 topic 一律派生自 unit.topic（建/改/拆篇/
改单元级联）；未挂单元的篇目 topic 才由教师显式给定。
情景缺失降级：主题没有对应情景问答题时，练习/换题/发布都不再 404。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from tests.utils.credential import make_student


def _make_unit(
    client: TestClient, headers: dict, topic: str, title: str, order: int = 90
) -> dict:
    return client.post(
        "/api/v1/admin/units",
        json={"order_index": order, "title": title, "topic": topic},
        headers=headers,
    ).json()


def _make_passage(
    client: TestClient,
    headers: dict,
    title: str,
    topic: str,
    unit_id: str | None,
) -> dict:
    return client.post(
        "/api/v1/admin/passages",
        json={
            "slug": f"th-{uuid.uuid4().hex[:8]}",
            "title": title,
            "topic": topic,
            "cefr_band": "B1",
            "text": "First paragraph about islands.\nSecond paragraph about tides.",
            "suggested_seconds": 30,
            **({"unit_id": unit_id} if unit_id else {}),
        },
        headers=headers,
    ).json()


def test_passage_topic_derives_from_unit(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """挂单元篇目的主题始终等于单元主题：建/改篇目、改单元都一样。"""
    headers = superuser_token_headers
    unit = _make_unit(client, headers, "Travel", "Travel Unit")

    # 创建时显式传入的 topic 被派生值覆盖
    passage = _make_passage(client, headers, "Trip", "WRONG", unit["id"])
    assert passage["topic"] == "Travel"

    # 更新时显式传入 topic 也不生效
    resp = client.put(
        f"/api/v1/admin/passages/{passage['id']}",
        json={"topic": "Other"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["topic"] == "Travel"

    # 单元改主题 → 属下篇目级联跟随
    resp = client.put(
        f"/api/v1/admin/units/{unit['id']}", json={"topic": "Food"}, headers=headers
    )
    assert resp.status_code == 200
    topics = {
        p["id"]: p["topic"]
        for p in client.get("/api/v1/admin/passages", headers=headers).json()
    }
    assert topics[passage["id"]] == "Food"

    # 单元主题不可设为 null，否则属下篇目会跟着写入非空列而触发 500。
    invalid = client.put(
        f"/api/v1/admin/units/{unit['id']}",
        json={"topic": None},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_passage_rejects_unknown_unit(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/admin/passages",
        json={
            "title": "Missing unit",
            "text": "A short passage.",
            "unit_id": str(uuid.uuid4()),
        },
        headers=superuser_token_headers,
    )
    assert response.status_code == 422


def test_unattached_passage_topic_is_free(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """未挂单元的篇目主题自管：显式给值生效，空串/null 清空不再 500。"""
    headers = superuser_token_headers
    passage = _make_passage(client, headers, "Solo", "Solo Topic", None)
    assert passage["topic"] == "Solo Topic"

    # 显式清空：空串归一为空串（历史上传 null 会落到非空列直接 500）
    for payload in ({"topic": ""}, {"topic": None}):
        resp = client.put(
            f"/api/v1/admin/passages/{passage['id']}", json=payload, headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["topic"] == ""

    # 挂上单元后主题即被接管
    unit = _make_unit(client, headers, "Travel", "Attach Unit", order=91)
    resp = client.put(
        f"/api/v1/admin/passages/{passage['id']}",
        json={"unit_id": unit["id"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["topic"] == "Travel"

    # 摘下单元（unit_id 置空）后 topic 保留派生值，不再被接管
    resp = client.put(
        f"/api/v1/admin/passages/{passage['id']}",
        json={"unit_id": None},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["topic"] == "Travel"


def test_split_passage_carries_unit_topic(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """拆篇走同一派生规则：新篇目主题等于单元主题。"""
    headers = superuser_token_headers
    unit = _make_unit(client, headers, "Travel", "Split Unit", order=92)
    passage = _make_passage(client, headers, "Long Trip", "WRONG", unit["id"])

    resp = client.post(f"/api/v1/admin/passages/{passage['id']}/split", headers=headers)
    assert resp.status_code == 200
    created_ids = set(resp.json()["passage_ids"])
    assert len(created_ids) >= 2
    topics = {
        p["id"]: p["topic"]
        for p in client.get("/api/v1/admin/passages", headers=headers).json()
    }
    assert all(topics[pid] == "Travel" for pid in created_ids)


def test_missing_scenario_degrades_explore_round(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """主题没有情景问答题：探索轮/换题/单元发布全部优雅降级，不再 404。"""
    headers = superuser_token_headers
    # 主题 Island 不建对应情景
    unit = _make_unit(client, headers, "Island", "Island Unit", order=93)
    passage = _make_passage(client, headers, "Island Life", "WRONG", unit["id"])
    client.post(
        f"/api/v1/admin/passages/{passage['id']}/sentences",
        json={"order_index": 0, "text": "Islands are quiet."},
        headers=headers,
    )

    student = make_student(db, client, "DEMO01", "降级同学")
    explore = client.post(
        "/api/v1/classes/DEMO01/explore",
        json={"unit_id": unit["id"]},
        headers=student["headers"],
    )
    assert explore.status_code == 200, explore.text
    session_id = explore.json()["session_id"]

    # /today：朗读/复述照常，问答题缺席且 questions_exhausted=True
    today = client.get(
        "/api/v1/classes/DEMO01/today",
        params={"session_id": session_id},
        headers=student["headers"],
    )
    assert today.status_code == 200
    plan = today.json()
    assert [i for i in plan["items"] if i["type"] == "question"] == []
    assert any(i["type"] == "repeat" for i in plan["items"])
    assert plan["questions_exhausted"] is True

    # 换一题：优雅返回无题而非 404
    nxt = client.get(
        "/api/v1/classes/DEMO01/next-question",
        params={"session_id": session_id},
        headers=student["headers"],
    )
    assert nxt.status_code == 200
    body = nxt.json()
    assert body["question"] is None
    assert body["exhausted"] is True

    # 单元指派发布：问答快照跳过，朗读/复述照常发布
    try:
        pub = client.put(
            "/api/v1/classes/DEMO01/assignment",
            json={"unit_id": unit["id"]},
            headers=headers,
        )
        assert pub.status_code == 200, pub.text
        other = make_student(db, client, "DEMO01", "降级同学乙")
        plan2 = client.get(
            "/api/v1/classes/DEMO01/today", headers=other["headers"]
        ).json()
        assert [i for i in plan2["items"] if i["type"] == "question"] == []
        assert any(i["type"] == "repeat" for i in plan2["items"])
    finally:
        # 走 API 清除指派：归档已发布练习，恢复自主练习（测试库跨文件共享）
        cleared = client.put(
            "/api/v1/classes/DEMO01/assignment",
            json={"unit_id": None},
            headers=headers,
        )
        assert cleared.status_code == 200
