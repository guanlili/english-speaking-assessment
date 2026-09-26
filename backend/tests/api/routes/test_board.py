"""老师名单表（board）与并发上传测试。

并发测试走真实线程池（不覆写评分提交器），需要把 worker 的引擎指向
测试库，否则评分线程会连开发库找不到作答行。BDD B：40 人同时停止录音，
老师表最终到齐，允许先显示「评分中」。
"""

import concurrent.futures
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

import app.core.db as core_db
from app.api.deps import get_scoring_submitter
from app.core.config import settings
from app.main import app
from app.models import Attempt
from app.scoring import worker

CLASS_STUDENTS = 40
SCORING_WAIT_TIMEOUT_S = 60.0


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None]:
    """音频落临时目录，评分同步执行（本文件只需 inline 形态）。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter
    yield None
    app.dependency_overrides.pop(get_scoring_submitter, None)


@pytest.fixture
def thread_pool_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """真实线程池评分 + 音频落临时目录 + worker 引擎指向测试库。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(core_db, "engine", db.get_bind())


def _join(client: TestClient, name: str) -> Any:
    resp = client.post("/api/v1/classes/DEMO01/join", json={"display_name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit_repeat(
    client: TestClient, item_id: str, student_id: str, session_id: str
) -> Any:
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"bytes", "audio/webm")},
        data={
            "item_type": "repeat",
            "item_id": item_id,
            "duration_s": "5.0",
            "student_id": student_id,
            "session_id": session_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_board_empty_classroom(client: TestClient) -> None:
    resp = client.get("/api/v1/classes/DEMO01/board")
    assert resp.status_code == 200
    data = resp.json()
    assert data["classroom_code"] == "DEMO01"
    assert data["students"] == []
    assert data["submitted_count"] == 0
    assert len(data["items"]) == 3  # 复述句骨架


def test_board_unknown_classroom_404(client: TestClient) -> None:
    assert client.get("/api/v1/classes/NOPE00/board").status_code == 404


def test_board_aggregates_students(client: TestClient, inline_scoring: None) -> None:
    """两个学生：一个答完所有题，一个只答一句——聚合正确且排序合理。"""
    alice = _join(client, "Alice")
    bob = _join(client, "Bob")

    alice_plan = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": alice["id"]}
    ).json()
    # Alice 全部答完（mock 引擎）
    for item in alice_plan["items"]:
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", item["id"])},
            data={
                "item_type": item["type"],
                "item_id": item["id"],
                "duration_s": "5.0",
                "student_id": alice["id"],
                "session_id": alice_plan["session_id"],
            },
        )
        assert resp.status_code == 200
    # Bob 只答第一句复述
    bob_plan = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": bob["id"]}
    ).json()
    first_repeat = bob_plan["items"][0]
    _submit_repeat(client, first_repeat["id"], bob["id"], bob_plan["session_id"])

    data = client.get("/api/v1/classes/DEMO01/board").json()
    assert data["submitted_count"] == 2
    assert data["pending_count"] == 0

    by_name = {s["display_name"]: s for s in data["students"]}
    alice_row = by_name["Alice"]
    bob_row = by_name["Bob"]
    assert alice_row["done_count"] == alice_row["total_count"]
    assert alice_row["repeat_avg"] is not None
    assert alice_row["question_avg"] is not None
    assert bob_row["done_count"] == 1
    assert bob_row["repeat_avg"] is not None
    assert bob_row["question_avg"] is None
    # 完成多的排前面
    assert data["students"][0]["display_name"] == "Alice"


def test_attempt_audio_roundtrip(client: TestClient, inline_scoring: None) -> None:
    """音频回放：上传的字节能原样取回（老师表点开听）。"""
    student = _join(client, "Audio 测试")
    plan = client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": student["id"]}
    ).json()
    first = plan["items"][0]
    payload = b"fake-audio-bytes-for-roundtrip"
    created = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", payload, "audio/webm")},
        data={
            "item_type": "repeat",
            "item_id": first["id"],
            "duration_s": "5.0",
            "student_id": student["id"],
            "session_id": plan["session_id"],
        },
    ).json()

    resp = client.get(f"/api/v1/attempts/{created['id']}/audio")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"].startswith("audio/webm")

    assert client.get(f"/api/v1/attempts/{uuid.uuid4()}/audio").status_code == 404


def test_classroom_40_concurrent_submissions(
    client: TestClient,
    thread_pool_scoring: None,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    """BDD B：40 人同时各交 1 条 → 全部最终出分，board 到齐。

    用独立新建的课堂隔离（前面的测试也在 DEMO01 里留过学生）。
    """
    created = client.post(
        "/api/v1/classes",
        json={"class_size": CLASS_STUDENTS},
        headers=superuser_token_headers,
    )
    assert created.status_code == 200, created.text
    code = created.json()["code"]

    students = []
    for i in range(CLASS_STUDENTS):
        resp = client.post(
            f"/api/v1/classes/{code}/join", json={"display_name": f"学生{i:02d}"}
        )
        assert resp.status_code == 200
        students.append(resp.json())

    plans = {}
    for student in students:
        plan = client.get(
            f"/api/v1/classes/{code}/today", params={"student_id": student["id"]}
        ).json()
        plans[student["id"]] = plan

    def upload(args: tuple[str, dict]) -> str:
        sid, plan = args
        first_item = plan["items"][0]
        return _submit_repeat(client, first_item["id"], sid, plan["session_id"])["id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        attempt_ids = list(pool.map(upload, list(plans.items())))

    assert len(attempt_ids) == CLASS_STUDENTS
    # 无一因超时/校验丢失
    assert all(attempt_ids)

    # 等待后台评分全部完成（默认 2 worker，mock 引擎很快）
    attempt_uuids = [uuid.UUID(aid) for aid in attempt_ids]
    deadline = time.monotonic() + SCORING_WAIT_TIMEOUT_S
    rows: Sequence[Attempt] = []
    while time.monotonic() < deadline:
        # 独立短会话查询，避免复用长事务 Session 的快照
        with Session(db.get_bind()) as poll:
            rows = poll.exec(
                select(Attempt).where(col(Attempt.id).in_(attempt_uuids))
            ).all()
        if len(rows) == CLASS_STUDENTS and all(
            r.status in ("done", "failed") for r in rows
        ):
            break
        time.sleep(0.5)
    else:
        pytest.fail("评分未在限时内完成")

    assert all(r.status == "done" for r in rows)
    assert all(r.transcript for r in rows)

    data = client.get(f"/api/v1/classes/{code}/board").json()
    assert data["submitted_count"] == CLASS_STUDENTS
    assert data["pending_count"] == 0
    submitted = [s for s in data["students"] if s["done_count"] >= 1]
    assert len(submitted) == CLASS_STUDENTS
