"""关卡地图（P2）：单元路径、解锁规则、今日篇目按路径推进。"""

import uuid
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.deps import get_scoring_submitter
from app.core.config import settings
from app.main import app
from app.scoring import worker


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None]:
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter
    yield None
    app.dependency_overrides.pop(get_scoring_submitter, None)


def _join(client: TestClient, name: str) -> Any:
    resp = client.post("/api/v1/classes/DEMO01/join", json={"display_name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_unit_passage(
    db: Session, headers: dict, client: TestClient, order: int, title: str
) -> dict:
    """建第二/第三个单元 + 篇目（第一个由种子提供）。"""
    unit = client.post(
        "/api/v1/admin/units",
        json={"order_index": order, "title": title, "topic": "Pets"},
        headers=headers,
    ).json()
    passage = client.post(
        "/api/v1/admin/passages",
        json={
            "slug": f"unit-{order}-{uuid.uuid4().hex[:6]}",
            "title": f"{title} passage",
            "topic": "Pets",
            "cefr_band": "B1",
            "text": "Cats are quiet and clean. They sleep a lot.",
            "suggested_seconds": 30,
            "unit_id": unit["id"],
        },
        headers=headers,
    ).json()
    # 复述句（供今日 5 题结构）
    for i, text in enumerate(
        ["Cats are quiet.", "They sleep a lot every day.", "I like cats and dogs."]
    ):
        client.post(
            f"/api/v1/admin/passages/{passage['id']}/sentences",
            json={"order_index": i, "text": text, "suggested_seconds": 6},
            headers=headers,
        )
    return {"unit": unit, "passage": passage}


def _finish_round(client: TestClient, plan: dict, student_id: str) -> None:
    for item in plan["items"]:
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", "audio/webm")},
            data={
                "item_type": item["type"],
                "item_id": item["id"],
                "duration_s": "6.0",
                "student_id": student_id,
                "session_id": plan["session_id"],
            },
        )
        assert resp.status_code == 200, resp.text


def test_path_single_unit_unlocked(client: TestClient, inline_scoring: None) -> None:
    """种子只有一个单元：第一关永远解锁。"""
    student = _join(client, "路径同学")
    resp = client.get(
        "/api/v1/classes/DEMO01/path", params={"student_id": student["id"]}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["unlock_all"] is False
    assert len(data["units"]) == 1
    assert data["units"][0]["locked"] is False
    assert data["units"][0]["rounds_done"] == 0
    assert data["units"][0]["passage_id"] is not None


def test_sequential_unlock_and_advance(
    client: TestClient,
    inline_scoring: None,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    """两个单元：第二关锁 → 完成第一关一轮 → 解锁，今日篇目推进。"""
    _make_unit_passage(db, superuser_token_headers, client, 1, "Unit 2")

    student = _join(client, "闯关同学")
    # 第二关锁定
    path = client.get(
        "/api/v1/classes/DEMO01/path", params={"student_id": student["id"]}
    ).json()
    assert len(path["units"]) == 2
    assert path["units"][1]["locked"] is True

    # 今日篇目仍是第一关
    plan = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": student["id"]}
    ).json()

    # 完成第一关一轮（结算由 /today 聚合触发，先拉一次）
    _finish_round(client, plan, student["id"])
    client.get("/api/v1/classes/DEMO01/today", params={"student_id": student["id"]})
    path2 = client.get(
        "/api/v1/classes/DEMO01/path", params={"student_id": student["id"]}
    ).json()
    assert path2["units"][0]["rounds_done"] == 1
    assert path2["units"][0]["best_stars"] is not None
    assert path2["units"][1]["locked"] is False

    # 老师全开开关也生效
    classroom_id = client.get(
        "/api/v1/admin/classrooms", headers=superuser_token_headers
    ).json()[0]["id"]
    updated = client.put(
        f"/api/v1/admin/classrooms/{classroom_id}",
        json={"unlock_all": True},
        headers=superuser_token_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["unlock_all"] is True


def test_unit_crud(client: TestClient, superuser_token_headers: dict) -> None:
    created = client.post(
        "/api/v1/admin/units",
        json={"order_index": 9, "title": "临时单元", "topic": "Test"},
        headers=superuser_token_headers,
    )
    assert created.status_code == 200
    unit = created.json()

    upd = client.put(
        f"/api/v1/admin/units/{unit['id']}",
        json={"title": "改名单元"},
        headers=superuser_token_headers,
    )
    assert upd.json()["title"] == "改名单元"

    listing = client.get("/api/v1/admin/units", headers=superuser_token_headers)
    assert any(u["id"] == unit["id"] for u in listing.json())

    assert (
        client.delete(
            f"/api/v1/admin/units/{unit['id']}", headers=superuser_token_headers
        ).status_code
        == 200
    )


# ── 课堂指派（教学工具定位）─────────────────────────────────────────


def test_assignment_directs_today_for_whole_class(
    client: TestClient,
    inline_scoring: None,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    """老师指派 Unit 2 → 全班 /today 都练 Unit 2 的篇目（无视个人路径）。"""
    second = _make_unit_passage(db, superuser_token_headers, client, 1, "Unit 2")

    alice = _join(client, "甲同学")
    resp = client.put(
        "/api/v1/classes/DEMO01/assignment",
        json={"unit_id": second["unit"]["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Unit 2"

    plan = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": alice["id"]}
    ).json()
    assert plan["assigned_unit_title"] == "Unit 2"
    # 篇目句子来自 Unit 2 的正文（Cats are quiet...）
    first_text = plan["items"][0]["text"]
    assert "Cats" in first_text or "cats" in first_text

    # 清除指派 → 回退个人路径（第一单元）
    cleared = client.put("/api/v1/classes/DEMO01/assignment", json={"unit_id": None})
    assert cleared.status_code == 200
    plan2 = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": alice["id"]}
    ).json()
    assert plan2["assigned_unit_title"] is None


def test_assignment_invalid_unit_404(client: TestClient) -> None:
    resp = client.put(
        "/api/v1/classes/DEMO01/assignment",
        json={"unit_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


def test_path_and_board_expose_assignment(
    client: TestClient, superuser_token_headers: dict, db: Session
) -> None:
    """path 返回 assignment 且被指派单元解除锁定；board 同步显示。"""
    second = _make_unit_passage(db, superuser_token_headers, client, 1, "Unit 2")
    student = _join(client, "乙同学")

    client.put(
        "/api/v1/classes/DEMO01/assignment",
        json={"unit_id": second["unit"]["id"]},
    )
    path = client.get(
        "/api/v1/classes/DEMO01/path", params={"student_id": student["id"]}
    ).json()
    assert path["assignment"]["title"] == "Unit 2"
    assert path["units"][1]["locked"] is False  # 指派豁免锁定

    board = client.get("/api/v1/classes/DEMO01/board").json()
    assert board["assignment"]["title"] == "Unit 2"

    # 清理：恢复无指派状态，避免影响其他测试
    client.put("/api/v1/classes/DEMO01/assignment", json={"unit_id": None})


def test_list_units_public_with_code(client: TestClient) -> None:
    resp = client.get("/api/v1/classes/DEMO01/units")
    assert resp.status_code == 200
    titles = [u["title"] for u in resp.json()]
    assert any("Unit 1" in t for t in titles)
    assert client.get("/api/v1/classes/NOPE00/units").status_code == 404


# ── 主题探索（自由练习）─────────────────────────────────────────────


def test_explore_session_lifecycle(
    client: TestClient,
    inline_scoring: None,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    """探索：按单元开轮、当日复用、today 可取计划、教师面板不计入完成率。"""
    second = _make_unit_passage(db, superuser_token_headers, client, 1, "Unit 2")
    student = _join(client, "探索侠")

    # 未加入指派 → today 默认第一单元；explore 用第二单元
    resp = client.post(
        "/api/v1/classes/DEMO01/explore",
        json={"unit_id": second["unit"]["id"], "student_id": student["id"]},
    )
    assert resp.status_code == 200, resp.text
    explore = resp.json()

    # 当日复用同一 explore 会话
    again = client.post(
        "/api/v1/classes/DEMO01/explore",
        json={"unit_id": second["unit"]["id"], "student_id": student["id"]},
    )
    assert again.json()["session_id"] == explore["session_id"]

    # today?session_id 返回探索轮计划（Unit 2 的复述句）
    plan = client.get(
        "/api/v1/classes/DEMO01/today",
        params={"student_id": student["id"], "session_id": explore["session_id"]},
    ).json()
    assert "Cats" in plan["items"][0]["text"] or "cats" in plan["items"][0]["text"]

    # 默认 today 仍是课堂轮（第一单元），两者互不干扰
    daily_plan = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": student["id"]}
    ).json()
    assert daily_plan["session_id"] != explore["session_id"]

    # 他人会话 → 404
    other = _join(client, "别人")
    assert (
        client.get(
            "/api/v1/classes/DEMO01/today",
            params={
                "student_id": other["id"],
                "session_id": explore["session_id"],
            },
        ).status_code
        == 404
    )

    # 探索轮的作答不进教师面板完成率
    for item in plan["items"]:
        _resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", "audio/webm")},
            data={
                "item_type": item["type"],
                "item_id": item["id"],
                "duration_s": "6.0",
                "student_id": student["id"],
                "session_id": explore["session_id"],
            },
        )
        assert _resp.status_code == 200
    board = client.get("/api/v1/classes/DEMO01/board").json()
    row = next(s for s in board["students"] if s["display_name"] == "探索侠")
    assert row["done_count"] == 0  # 探索不计入今日课堂统计
