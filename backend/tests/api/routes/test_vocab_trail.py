"""词汇分析集成（问答作答写入 vocab）与轨迹/面板增强（US-07/09/10）。"""

import uuid
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_scoring_submitter
from app.core.config import settings
from app.main import app
from app.models import WordlistEntry
from app.scoring import worker
from app.scoring.base import ScoringError


class FakeAsr:
    name = "fake"

    def __init__(self, transcript: str) -> None:
        self.transcript = transcript

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        return self.transcript


@pytest.fixture
def scripted_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[Callable[[str], None]]:
    """评分同步执行 + 可设定的固定转写。返回 set_transcript(text)。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter

    def set_transcript(transcript: str) -> None:
        monkeypatch.setattr(worker, "build_asr_provider", lambda: FakeAsr(transcript))

    set_transcript("i like dogs because they are friendly")
    yield set_transcript
    app.dependency_overrides.pop(get_scoring_submitter, None)


def _join(client: TestClient, name: str) -> Any:
    resp = client.post("/api/v1/classes/DEMO01/join", json={"display_name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _plan(client: TestClient, student_id: str) -> Any:
    return client.get(
        "/api/v1/classes/DEMO01/today", params={"student_id": student_id}
    ).json()


def _submit(client: TestClient, item: dict, student_id: str, session_id: str) -> Any:
    resp = client.post(
        "/api/v1/attempts",
        files={"audio": ("a.webm", b"bytes", "audio/webm")},
        data={
            "item_type": item["type"],
            "item_id": item["id"],
            "duration_s": "5.0",
            "student_id": student_id,
            "session_id": session_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── US-07 词汇量与 CEFR ─────────────────────────────────────────────


def test_question_attempt_has_vocab_analysis(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    """问答作答评分后带词汇分析：命中词/覆盖率/CEFR 参考标签。"""
    student = _join(client, "词汇同学")
    plan = _plan(client, student["id"])
    question = next(i for i in plan["items"] if i["type"] == "question")
    # 转写含多个 B1 词：prefer loyal independent relax effort
    scripted_scoring(
        "i prefer loyal dogs because they help me relax with effort and "
        "independent habits at home"
    )
    attempt = _submit(client, question, student["id"], plan["session_id"])
    assert attempt["status"] == "done"
    vocab = attempt["vocab"]
    assert vocab is not None
    assert vocab["wordlist"]
    assert vocab["cefr"] in ("A2", "B1", "B2")
    hits: dict = vocab["hits"]
    assert "B1" in hits
    assert "prefer" in hits["B1"]
    assert 0 <= vocab["coverage"] <= 1


def test_repeat_attempt_has_no_vocab(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    """跟读参考文本的词不算学生词汇（PRD US-07）→ 复述作答 vocab 为 null。"""
    student = _join(client, "跟读同学")
    plan = _plan(client, student["id"])
    repeat = next(i for i in plan["items"] if i["type"] == "repeat")
    attempt = _submit(client, repeat, student["id"], plan["session_id"])
    assert attempt["vocab"] is None


def test_no_wordlist_shows_null_not_fabricated(
    client: TestClient,
    scripted_scoring: Callable[[str], None],
    db: Session,
) -> None:
    """BDD D：词表未配置 → vocab 为 null，界面显示「未配置词表」，不编造等级。"""
    from app.core.db import _seed_wordlist

    # 清空词表（测试库独立，安全），结束后恢复种子
    entries = db.exec(select(WordlistEntry)).all()
    for entry in entries:
        db.delete(entry)
    db.commit()
    try:
        student = _join(client, "无词表同学")
        plan = _plan(client, student["id"])
        question = next(i for i in plan["items"] if i["type"] == "question")
        attempt = _submit(client, question, student["id"], plan["session_id"])
        assert attempt["status"] == "done"
        assert attempt["vocab"] is None
    finally:
        _seed_wordlist(db)


# ── US-09 学生进步轨迹 ──────────────────────────────────────────────


def test_trail_aggregates_by_day(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    student = _join(client, "轨迹同学")
    plan = _plan(client, student["id"])
    # 答一题问答 + 一句复述
    scripted_scoring(
        "i prefer loyal dogs because they help me relax with effort and "
        "independent habits"
    )
    question = next(i for i in plan["items"] if i["type"] == "question")
    _submit(client, question, student["id"], plan["session_id"])
    scripted_scoring("dogs are friendly and loyal")
    repeat = next(i for i in plan["items"] if i["type"] == "repeat")
    _submit(client, repeat, student["id"], plan["session_id"])

    resp = client.get(
        "/api/v1/classes/DEMO01/trail", params={"student_id": student["id"]}
    )
    assert resp.status_code == 200
    trail = resp.json()
    assert trail["display_name"] == "轨迹同学"
    assert len(trail["sessions"]) == 1
    day = trail["sessions"][0]
    assert day["speaking_avg"] is not None  # 问答总评
    assert day["repeat_completeness_avg"] is not None  # 跟读完整度独立成列
    assert day["vocab_cefr"] in ("A2", "B1", "B2")
    assert day["attempt_count"] == 2


def test_trail_unknown_student_404(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/classes/DEMO01/trail", params={"student_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


def test_trail_empty_for_new_student(client: TestClient) -> None:
    student = _join(client, "新同学")
    resp = client.get(
        "/api/v1/classes/DEMO01/trail", params={"student_id": student["id"]}
    )
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []


# ── US-10 面板增强 ───────────────────────────────────────────────────


def test_board_band_distribution_and_inactive(
    client: TestClient, scripted_scoring: Callable[[str], None], db: Session
) -> None:
    """档位分布按学生当前档统计；新加入（<7 天）不算未练。"""
    _join(client, "面板同学")

    data = client.get("/api/v1/classes/DEMO01/board").json()
    assert data["band_distribution"].get("B1", 0) >= 1
    # 刚加入不到 7 天：不标记未练
    row = next(s for s in data["students"] if s["display_name"] == "面板同学")
    assert row["inactive_days7"] is False
    assert row["current_band"] == "B1"


def test_engine_failure_vocab_not_fabricated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db: Session
) -> None:
    """引擎失败：status=failed，vocab 为 null（不编造）。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        worker,
        "build_asr_provider",
        lambda: (_ for _ in ()).throw(ScoringError("引擎不可用")),
    )

    def override_submitter() -> Callable[[uuid.UUID], None]:
        def run(attempt_id: uuid.UUID) -> None:
            with Session(db.get_bind()) as session:
                worker.process_attempt(session, attempt_id)

        return run

    app.dependency_overrides[get_scoring_submitter] = override_submitter
    try:
        student = _join(client, "失败同学")
        plan = _plan(client, student["id"])
        question = next(i for i in plan["items"] if i["type"] == "question")
        attempt = _submit(client, question, student["id"], plan["session_id"])
        assert attempt["status"] == "failed"
        assert attempt["vocab"] is None
    finally:
        app.dependency_overrides.pop(get_scoring_submitter, None)


def test_trail_band_change_after_upgrade(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    """复述全对（高完整度+达标语速）→ 问答档升 → trail 标记 up。"""
    student = _join(client, "升档同学")
    plan = _plan(client, student["id"])
    # 每句原文照读 + 语速 2.5 w/s 附近 → 完整度 100、流利度高
    repeats = [i for i in plan["items"] if i["type"] == "repeat"]
    for item in repeats:
        scripted_scoring(item["text"])
        words = len(item["text"].split())
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", "audio/webm")},
            data={
                "item_type": "repeat",
                "item_id": item["id"],
                "duration_s": str(round(words / 2.5, 1)),
                "student_id": student["id"],
                "session_id": plan["session_id"],
            },
        )
        assert resp.status_code == 200

    trail = client.get(
        "/api/v1/classes/DEMO01/trail", params={"student_id": student["id"]}
    ).json()
    assert trail["band_change"] == "up"


def test_trail_band_change_keep_when_partial(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    """只答一题（复述未全完成）→ 无调整 → band_change 为 null。"""
    student = _join(client, "未调档同学")
    plan = _plan(client, student["id"])
    first = plan["items"][0]
    scripted_scoring(first["text"])
    _submit(client, first, student["id"], plan["session_id"])

    trail = client.get(
        "/api/v1/classes/DEMO01/trail", params={"student_id": student["id"]}
    ).json()
    assert trail["band_change"] is None


def _finish_round(
    client: TestClient, plan: dict, student_id: str, transcripts_by_item: dict
) -> None:
    for item in plan["items"]:
        scripted = transcripts_by_item.get(item["id"], item["text"])
        resp = client.post(
            "/api/v1/attempts",
            files={"audio": ("a.webm", b"bytes", scripted)},
            data={
                "item_type": item["type"],
                "item_id": item["id"],
                "duration_s": "6.0",
                "student_id": student_id,
                "session_id": plan["session_id"],
            },
        )
        assert resp.status_code == 200, resp.text


def test_settlement_xp_stars_badge_on_today(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    """答完全轮 → /today 结算：1 星保底、XP 入账、首轮徽章、幂等。"""
    student = _join(client, "激励同学")
    plan = _plan(client, student["id"])
    _finish_round(client, plan, student["id"], {})

    data = _plan(client, student["id"])  # 再拉一次触发结算
    g = data["gamification"]
    assert g is not None
    assert g["session_stars"] == 1  # mock 转写分不高 → 保底 1 星
    assert g["xp"] == 5 * 10 + 1 * 5  # 5 题 ×10 + 1 星 ×5（无连胜奖励）
    assert g["streak_days"] == 1
    keys = [b["key"] for b in g["badges"]]
    assert "first_round" in keys

    # 幂等：再拉 today 不重复结算
    again = _plan(client, student["id"])["gamification"]
    assert again["xp"] == g["xp"]


def test_settlement_partial_round_not_settled(
    client: TestClient, scripted_scoring: Callable[[str], None]
) -> None:
    """只答部分题 → 不结算（stars/xp 保持初始）。"""
    student = _join(client, "未完成同学")
    plan = _plan(client, student["id"])
    first = plan["items"][0]
    _submit(client, first, student["id"], plan["session_id"])

    g = _plan(client, student["id"])["gamification"]
    assert g["session_stars"] is None
    assert g["xp"] == 0
