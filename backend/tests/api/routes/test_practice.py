"""练习接口的 API 流程测试。

评分提交器覆写为同步执行，走完 queued → done/failed 的完整状态机，
不依赖线程池与真实云引擎（引擎另有单元测试覆盖）。
"""

import uuid
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_scoring_submitter
from app.core.config import settings
from app.main import app
from app.models import Attempt
from app.scoring import worker
from app.scoring.base import ScoringError


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None]:
    """音频落盘到临时目录，评分改为请求线程内同步执行。

    注意：FastAPI 解析覆写函数自身的签名，因此覆写必须是零参工厂，
    返回真正的提交器（与 get_scoring_submitter 的形态一致）。
    """

    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter
    yield None
    app.dependency_overrides.pop(get_scoring_submitter, None)


def test_read_active_passage(client: TestClient) -> None:
    resp = client.get("/api/v1/practice/passage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "demo-pets"
    assert "friendly" in data["text"]
    assert data["is_active"] is True


def test_create_and_poll_attempt(
    client: TestClient,
    inline_scoring: None,
) -> None:
    passage_id = client.get("/api/v1/practice/passage").json()["id"]

    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("attempt.webm", b"fake-audio-bytes", "audio/webm")},
        data={
            "item_type": "passage",
            "item_id": passage_id,
            "duration_s": "12.5",
        },
    )
    assert resp.status_code == 200
    attempt = resp.json()
    # 提交即返回（不可协商 #4）：mock 引擎下同步完成，状态为 done
    assert attempt["status"] == "done"
    assert attempt["engine"] == "mock"
    assert attempt["transcript"]
    for key in ("completeness", "fluency", "overall"):
        assert 0 <= attempt[key] <= 100
    assert len(attempt["advice"]) <= 2
    assert "audio_path" not in attempt  # 存储路径不外泄

    polled = client.get(f"/api/v1/attempts/{attempt['id']}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "done"


def test_repractice_creates_new_attempt(
    client: TestClient,
    inline_scoring: None,
    db: Session,
) -> None:
    """US-03：再练一次新建一条作答，不覆盖旧记录。"""
    passage_id = client.get("/api/v1/practice/passage").json()["id"]
    before = len(db.exec(select(Attempt)).all())

    for _ in range(2):
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", "audio/webm")},
            data={
                "item_type": "passage",
                "item_id": passage_id,
                "duration_s": "10.0",
            },
        )
        assert resp.status_code == 200

    after = len(db.exec(select(Attempt)).all())
    assert after == before + 2


def test_short_recording_rejected(
    client: TestClient,
    inline_scoring: None,
) -> None:
    """US-02：短于 1 秒不打分。"""
    passage_id = client.get("/api/v1/practice/passage").json()["id"]
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"bytes", "audio/webm")},
        data={
            "item_type": "passage",
            "item_id": passage_id,
            "duration_s": "0.4",
        },
    )
    assert resp.status_code == 422


def test_scoring_failure_keeps_audio(
    client: TestClient,
    inline_scoring: None,
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
) -> None:
    """US-03 冲突：引擎失败时作答保留（failed + error），音频文件不删。"""
    monkeypatch.setattr(
        worker,
        "build_asr_provider",
        lambda: (_ for _ in ()).throw(ScoringError("引擎不可用")),
    )
    passage_id = client.get("/api/v1/practice/passage").json()["id"]

    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"keep-me", "audio/webm")},
        data={
            "item_type": "passage",
            "item_id": passage_id,
            "duration_s": "8.0",
        },
    )
    assert resp.status_code == 200
    attempt = resp.json()
    assert attempt["status"] == "failed"
    assert "引擎不可用" in attempt["error"]

    row = db.get(Attempt, uuid.UUID(attempt["id"]))
    assert row is not None and Path(row.audio_path).exists()


def test_unknown_attempt_404(client: TestClient) -> None:
    resp = client.get(f"/api/v1/attempts/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_unknown_passage_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"bytes", "audio/webm")},
        data={
            "item_type": "passage",
            "item_id": str(uuid.uuid4()),
            "duration_s": "5.0",
        },
    )
    assert resp.status_code == 404
