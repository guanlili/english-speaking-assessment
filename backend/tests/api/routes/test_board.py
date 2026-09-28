"""老师名单表（board）与并发上传测试。

并发测试走真实线程池（不覆写评分提交器），需要把 worker 的引擎指向
测试库，否则评分线程会连开发库找不到作答行。BDD B：40 人同时停止录音，
老师表最终到齐，允许先显示「评分中」。

账号制：学生 = 学号登录 JWT，请求带 Authorization 头（不再传
student_id/token 查询参数）。
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
from tests.utils.audio import wav_bytes, wav_upload
from tests.utils.credential import make_student

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


def _join(db: Session, client: TestClient, name: str) -> Any:
    """建学生账号 + 登录 + 入班 DEMO01，返回 {student, headers, user}。"""
    return make_student(db, client, "DEMO01", name)


def _submit_repeat(
    client: TestClient, item_id: str, headers: dict[str, str], session_id: str
) -> Any:
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(5.0)},
        data={
            "item_type": "repeat",
            "item_id": item_id,
            "duration_s": "5.0",
            "session_id": session_id,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(scope="module", autouse=True)
def teacher_auth(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    """教师端点（board/音频回放）需要登录：本模块默认带管理员身份。"""
    client.headers.update(superuser_token_headers)


def test_board_empty_classroom(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """新建空课堂的 board 应无学生数据。"""
    created = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    )
    assert created.status_code == 200
    code = created.json()["code"]
    resp = client.get(f"/api/v1/classes/{code}/board")
    assert resp.status_code == 200
    data = resp.json()
    assert data["classroom_code"] == code
    assert data["students"] == []
    assert data["submitted_count"] == 0
    assert data["completed_count"] == 0
    assert len(data["items"]) == 3  # 复述句骨架


def test_board_unknown_classroom_404(client: TestClient) -> None:
    assert client.get("/api/v1/classes/NOPE00/board").status_code == 404


def test_board_aggregates_students(
    client: TestClient, inline_scoring: None, db: Session
) -> None:
    """两个学生：一个答完所有题，一个只答一句——聚合正确且排序合理。"""
    alice = _join(db, client, "Alice")
    bob = _join(db, client, "Bob")

    alice_plan = client.get(
        "/api/v1/classes/DEMO01/today", headers=alice["headers"]
    ).json()
    # Alice 全部答完（mock 引擎）
    for item in alice_plan["items"]:
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(5.0)},
            data={
                "item_type": item["type"],
                "item_id": item["id"],
                "duration_s": "5.0",
                "session_id": alice_plan["session_id"],
            },
            headers=alice["headers"],
        )
        assert resp.status_code == 200
    # Bob 只答第一句复述
    bob_plan = client.get("/api/v1/classes/DEMO01/today", headers=bob["headers"]).json()
    first_repeat = bob_plan["items"][0]
    _submit_repeat(client, first_repeat["id"], bob["headers"], bob_plan["session_id"])

    data = client.get("/api/v1/classes/DEMO01/board").json()
    assert data["submitted_count"] == 2
    assert data["completed_count"] == 1  # Alice 完成全部，Bob 只做了 1 题
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


def test_attempt_audio_roundtrip(
    client: TestClient, inline_scoring: None, db: Session
) -> None:
    """音频回放：上传的字节能原样取回（老师表点开听）。"""
    student = _join(db, client, "Audio 测试")
    plan = client.get("/api/v1/classes/DEMO01/today", headers=student["headers"]).json()
    first = plan["items"][0]
    payload = wav_bytes(5.0)
    created = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.wav", payload, "audio/wav")},
        data={
            "item_type": "repeat",
            "item_id": first["id"],
            "duration_s": "5.0",
            "session_id": plan["session_id"],
        },
        headers=student["headers"],
    ).json()

    resp = client.get(f"/api/v1/attempts/{created['id']}/audio")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"].startswith("audio/wav")

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

    students = [
        make_student(db, client, code, f"学生{i:02d}") for i in range(CLASS_STUDENTS)
    ]

    # sid → (今日计划, 学生 JWT 头)：并发线程各带各的身份上传
    plans: dict[str, tuple[dict, dict[str, str]]] = {}
    for student in students:
        sid = student["student"]["id"]
        plan = client.get(
            f"/api/v1/classes/{code}/today", headers=student["headers"]
        ).json()
        plans[sid] = (plan, student["headers"])

    def upload(args: tuple[str, tuple[dict, dict[str, str]]]) -> str:
        _sid, (plan, headers) = args
        first_item = plan["items"][0]
        return _submit_repeat(client, first_item["id"], headers, plan["session_id"])[
            "id"
        ]

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
    assert data["completed_count"] == 0  # 每人只做了 1/5 题，不算整轮完成
    assert data["pending_count"] == 0
    submitted = [s for s in data["students"] if s["done_count"] >= 1]
    assert len(submitted) == CLASS_STUDENTS
