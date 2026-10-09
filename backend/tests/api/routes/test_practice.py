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
from app.models import Attempt, AttemptStatus, Passage
from app.scoring import worker
from app.scoring.base import ScoringError
from tests.utils.audio import wav_upload


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
        # 自动重试：评分失败后重排队列，继续处理到终态
        while True:
            with Session(db.get_bind()) as check:
                attempt = check.get(Attempt, attempt_id)
                if attempt is None or attempt.status != AttemptStatus.QUEUED:
                    break
            with Session(db.get_bind()) as session:
                worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter
    yield None
    app.dependency_overrides.pop(get_scoring_submitter, None)


def _demo_passage_id(db: Session) -> str:
    """初始化数据内置的演示篇目（原 /practice/passage 接口已随 MVP 演示形态移除）。"""
    passage = db.exec(select(Passage).where(Passage.slug == "demo-pets")).first()
    assert passage is not None
    return str(passage.id)


def test_create_and_poll_attempt(
    client: TestClient,
    inline_scoring: None,
    db: Session,
) -> None:
    passage_id = _demo_passage_id(db)

    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(12.5)},
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
    passage_id = _demo_passage_id(db)
    before = len(db.exec(select(Attempt)).all())

    for _ in range(2):
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(10.0)},
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
    db: Session,
) -> None:
    """US-02：短于 1 秒不打分。"""
    passage_id = _demo_passage_id(db)
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(0.4)},
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
    passage_id = _demo_passage_id(db)

    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(8.0)},
        data={
            "item_type": "passage",
            "item_id": passage_id,
            "duration_s": "8.0",
        },
    )
    assert resp.status_code == 200
    attempt = resp.json()
    assert attempt["status"] == "failed"
    # error 只暴露通用文案，不泄漏引擎异常原文（可能含上游 endpoint/配额细节）
    assert "评分服务暂时不可用" in attempt["error"]
    assert "引擎不可用" not in attempt["error"]

    row = db.get(Attempt, uuid.UUID(attempt["id"]))
    assert row is not None and Path(row.audio_path).exists()


def test_unknown_attempt_404(client: TestClient) -> None:
    resp = client.get(f"/api/v1/attempts/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_unknown_passage_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(5.0)},
        data={
            "item_type": "passage",
            "item_id": str(uuid.uuid4()),
            "duration_s": "5.0",
        },
    )
    assert resp.status_code == 404


def test_quick_feedback_committed_before_detail(
    client: TestClient,
    inline_scoring: None,
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
) -> None:
    """详细评价未执行时，分数与转写已经持久化并可轮询。"""
    from unittest.mock import Mock

    from app.core import db as db_module

    provider = Mock(name="asr")
    provider.name = "ark"
    provider.transcribe.return_value = "I like cats because they are friendly."
    detail_executor = Mock()
    monkeypatch.setattr(worker, "build_asr_provider", lambda: provider)
    monkeypatch.setattr(
        worker, "ensure_ark_supported", lambda audio, mime: (audio, mime)
    )
    monkeypatch.setattr(worker, "_resolve_read_aloud_item", lambda *_: None)
    monkeypatch.setattr(
        worker, "_resolve_question_prompt", lambda *_: ("Why cats?", "B1")
    )
    monkeypatch.setattr(worker, "_detail_executor", detail_executor)
    monkeypatch.setattr(db_module, "engine", db.get_bind())
    passage_id = _demo_passage_id(db)
    response = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(8.0)},
        data={"item_type": "passage", "item_id": passage_id, "duration_s": "8.0"},
    )
    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "done"
    assert data["overall"] is not None
    assert data["transcript"] == provider.transcribe.return_value
    assert data["rubric"] is not None
    assert data["rubric"]["status"] == "pending"
    # pending_since 记录详情阶段开始时刻（批次04：挂起超时按此判定）
    assert "pending_since" in data["rubric"]
    detail_executor.submit.assert_called_once()

    monkeypatch.setattr(worker, "_score_rubric", lambda *_: None)
    callback, *args = detail_executor.submit.call_args.args
    callback(*args)
    polled = client.get(f"/api/v1/attempts/{data['id']}").json()
    assert polled["status"] == "done"
    assert polled["overall"] == data["overall"]
    assert polled["rubric"] == {"status": "unavailable"}


def test_anonymous_submit_blocked_outside_local(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产/预发环境关闭匿名演示提交：会真实触发付费评分并占用全站队列。"""
    from app.api.routes import attempts as attempts_route

    monkeypatch.setattr(attempts_route.settings, "ENVIRONMENT", "production")
    passage_id = _demo_passage_id(db)
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(2.0)},
        data={
            "item_type": "passage",
            "item_id": passage_id,
            "duration_s": "2.0",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "演示提交未开放，请登录后使用"
