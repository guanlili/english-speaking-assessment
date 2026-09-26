"""课堂流程测试（US-04/05/06）：进入、今日计划、档位调整、换一题。

评分提交器覆写为同步执行；ASR 用可控的假引擎精确控制复述得分，
驱动升档/降档分支（US-05 验收口径）。
"""

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
from app.models import Attempt
from app.scoring import worker
from app.scoring.base import ScoringError


class FakeAsr:
    """按 item_type 返回可控转写：复述句原文（高完整度）或极短文本（低完整度）。"""

    name = "fake"

    def __init__(self, transcripts: dict[str, str] | None = None) -> None:
        self.transcripts = transcripts or {}

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        return self.transcripts.get(mime_type, "")


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[Callable[[dict[str, str]], None]]:
    """音频落盘临时目录，评分同步执行；返回设置假转写的函数。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter

    def set_transcripts(transcripts: dict[str, str]) -> None:
        monkeypatch.setattr(worker, "build_asr_provider", lambda: FakeAsr(transcripts))

    yield set_transcripts
    app.dependency_overrides.pop(get_scoring_submitter, None)


def _join(client: TestClient, name: str = "李雷", code: str = "DEMO01") -> Any:
    resp = client.post(f"/api/v1/classes/{code}/join", json={"display_name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _today(client: TestClient, student_id: str, code: str = "DEMO01") -> Any:
    return client.get(
        f"/api/v1/classes/{code}/today", params={"student_id": student_id}
    )


def _submit(
    client: TestClient,
    item_type: str,
    item_id: str,
    student_id: str,
    session_id: str,
    duration: float = 6.0,
) -> Any:
    return client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"bytes", "audio/webm")},
        data={
            "item_type": item_type,
            "item_id": item_id,
            "duration_s": str(duration),
            "student_id": student_id,
            "session_id": session_id,
        },
    )


# ── US-04 加入课堂 ───────────────────────────────────────────────────


def test_join_unknown_code_404(client: TestClient) -> None:
    resp = client.post("/api/v1/classes/NOPE00/join", json={"display_name": "李雷"})
    assert resp.status_code == 404


def test_join_empty_name_422(client: TestClient) -> None:
    resp = client.post("/api/v1/classes/DEMO01/join", json={"display_name": "  "})
    assert resp.status_code == 422


def test_join_returns_student(client: TestClient) -> None:
    data = _join(client, "李雷")
    assert data["display_name"] == "李雷"
    assert data["suffix"] is None
    assert data["current_band"] == "B1"


def test_join_duplicate_name_gets_suffix(client: TestClient) -> None:
    first = _join(client, "李雷")
    second = _join(client, "李雷")
    assert first["id"] != second["id"]
    assert second["suffix"] is not None and len(second["suffix"]) == 4


# ── US-05 今日计划与档位 ─────────────────────────────────────────────


def test_today_plan_shape(
    client: TestClient,
    inline_scoring: Any,
) -> None:
    student_id = _join(client)["id"]
    resp = _today(client, student_id)
    assert resp.status_code == 200
    plan = resp.json()
    repeats = [i for i in plan["items"] if i["type"] == "repeat"]
    questions = [i for i in plan["items"] if i["type"] == "question"]
    assert len(repeats) == 3
    assert len(questions) == 2
    # 首次进入默认中档（PRD §6）
    assert plan["band"] == "B1"
    assert all(q["band"] == "B1" for q in questions)
    # 两次调用同一天同一会话（刷新恢复进度）
    again = _today(client, student_id).json()
    assert again["session_id"] == plan["session_id"]


def test_today_unknown_student_404(
    client: TestClient,
    inline_scoring: Any,
) -> None:
    assert _today(client, str(uuid.uuid4())).status_code == 404


def _finish_repeats(
    client: TestClient, plan: dict, student_id: str, transcripts: dict[str, str]
) -> None:
    """把 3 句复述全部答完（对每句用假转写控制得分）。"""
    repeats = [i for i in plan["items"] if i["type"] == "repeat"]
    for item in repeats:
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", item["id"])},
            data={
                "item_type": "repeat",
                "item_id": item["id"],
                "duration_s": "6.0",
                "student_id": student_id,
                "session_id": plan["session_id"],
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "done"


def test_high_completeness_upgrades_band(
    client: TestClient, inline_scoring: Any
) -> None:
    """US-05：复述完整度 ≥80 且流利度达标 → 问答升到 B2。"""
    student_id = _join(client)["id"]
    plan = _today(client, student_id).json()
    repeats = [i for i in plan["items"] if i["type"] == "repeat"]
    # 每句原文照读 + 合适语速 → 完整度 100
    transcripts = {item["id"]: item["text"] for item in repeats}
    inline_scoring(transcripts)
    _finish_repeats(client, plan, student_id, transcripts)

    resp = _today(client, student_id)
    plan2 = resp.json()
    assert plan2["band"] == "B2"
    questions = [i for i in plan2["items"] if i["type"] == "question"]
    assert all(q["band"] == "B2" for q in questions)


def test_low_completeness_downgrades_band(
    client: TestClient, inline_scoring: Any
) -> None:
    """US-05：跟读完整度低于 50% → 问答为低档 A2。"""
    student_id = _join(client)["id"]
    plan = _today(client, student_id).json()
    repeats = [i for i in plan["items"] if i["type"] == "repeat"]
    transcripts = {item["id"]: "hello" for item in repeats}
    inline_scoring(transcripts)
    _finish_repeats(client, plan, student_id, transcripts)

    plan2 = _today(client, student_id).json()
    assert plan2["band"] == "A2"
    questions = [i for i in plan2["items"] if i["type"] == "question"]
    assert all(q["band"] == "A2" for q in questions)


# ── US-06 换一题 ─────────────────────────────────────────────────────


def test_next_question_then_exhausted(
    client: TestClient,
    inline_scoring: Any,
) -> None:
    """换一题给出同主题同档未做的题；做完后 exhausted=true。"""
    student_id = _join(client)["id"]
    plan = _today(client, student_id).json()

    def next_q() -> Any:
        return client.get(
            "/api/v1/classes/DEMO01/next-question",
            params={"student_id": student_id},
        )

    # B1 种子有 3 道题：今日占 2 道，换一题先拿到第 3 道
    seen: list[str] = []
    for _ in range(3):
        resp = next_q()
        question = resp.json()["question"]
        assert question is not None
        assert question["band"] == "B1"
        assert question["id"] not in seen
        seen.append(question["id"])
        # 学生答掉这题（标记为已做）
        _submit(client, "question", question["id"], student_id, plan["session_id"])

    # 3 道全做完 → exhausted（不再返回新题）
    resp = next_q()
    assert resp.json()["question"] is None
    assert resp.json()["exhausted"] is True


def test_question_attempt_scores_open_response(
    client: TestClient, inline_scoring: Any
) -> None:
    """问答作答走开放题评分：只有总评/流利度/一句建议，无完整度。"""
    inline_scoring({"question": "i like dogs because they are friendly"})
    student_id = _join(client)["id"]
    plan = _today(client, student_id).json()
    question = next(i for i in plan["items"] if i["type"] == "question")

    resp = _submit(client, "question", question["id"], student_id, plan["session_id"])
    assert resp.status_code == 200
    attempt = resp.json()
    assert attempt["status"] == "done"
    assert attempt["completeness"] is None  # 开放题没有参考文本
    assert attempt["overall"] is not None
    assert len(attempt["advice"]) == 1


def test_attempt_with_foreign_session_rejected(
    client: TestClient,
    inline_scoring: Any,
) -> None:
    """会话不属于该学生 → 422（不能借别人的 session 交作业）。"""
    alice = _join(client, "Alice")["id"]
    bob = _join(client, "Bob")["id"]
    bob_plan = _today(client, bob).json()
    question = next(i for i in bob_plan["items"] if i["type"] == "question")

    resp = _submit(client, "question", question["id"], alice, bob_plan["session_id"])
    assert resp.status_code == 422


def test_scoring_failure_preserves_attempt(
    client: TestClient,
    inline_scoring: Any,
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
) -> None:
    """引擎失败：作答落为 failed 并保留 error，音频不删（US-03 冲突口径）。"""
    monkeypatch.setattr(
        worker,
        "build_asr_provider",
        lambda: (_ for _ in ()).throw(ScoringError("引擎不可用")),
    )
    student_id = _join(client)["id"]
    plan = _today(client, student_id).json()
    repeat = next(i for i in plan["items"] if i["type"] == "repeat")

    resp = _submit(client, "repeat", repeat["id"], student_id, plan["session_id"])
    attempt = resp.json()
    assert attempt["status"] == "failed"
    assert "引擎不可用" in attempt["error"]

    row = db.get(Attempt, uuid.UUID(attempt["id"]))
    assert row is not None and Path(row.audio_path).exists()


def test_create_classroom_requires_superuser(client: TestClient) -> None:
    """匿名创建课堂 → 401（课堂码由老师/管理员生成）。"""
    resp = client.post("/api/v1/classes", json={"class_size": 40})
    assert resp.status_code == 401


def test_create_classroom_as_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/v1/classes", json={"class_size": 30}, headers=superuser_token_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["code"]) == 6
    assert data["class_size"] == 30
