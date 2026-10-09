"""US-08 rubric 评分器单元测试（纯函数 + MockTransport + worker 降级）。"""

import json
import uuid

import httpx
import pytest
from sqlmodel import Session

from app.models import Attempt, AttemptStatus
from app.scoring import rubric as rubric_module
from app.scoring import worker
from app.scoring.rubric import (
    DIMENSION_MAX,
    MAX_ADVICE,
    MAX_UPGRADES,
    RUBRIC_TO_SCORE,
    ArkRubricScorer,
    RubricParseError,
    build_rubric_user_prompt,
    map_to_mock_score,
    parse_rubric_response,
)


def test_mock_score_mapping_bounds() -> None:
    assert map_to_mock_score(0) == 0
    assert map_to_mock_score(16) == 9
    assert map_to_mock_score(-3) == 0  # 越界截断
    assert map_to_mock_score(99) == 9
    assert len(RUBRIC_TO_SCORE) == 17


def test_parse_rubric_plain_json() -> None:
    content = json.dumps(
        {
            "fluency": 3,
            "vocabulary": 2,
            "grammar": 2,
            "task": 4,
            "advice": ["你说的 “i like dog” 可以改成 i like dogs"],
            "upgrades": ["i like dog → i really enjoy keeping dogs"],
        }
    )
    scores = parse_rubric_response(content)
    assert (scores.fluency, scores.vocabulary, scores.grammar, scores.task) == (
        3,
        2,
        2,
        4,
    )
    assert scores.mock_score == map_to_mock_score(11)
    assert len(scores.advice) == 1
    assert len(scores.upgrades) == 1


def test_parse_rubric_strips_code_fences() -> None:
    content = '```json\n{"fluency": 4, "vocabulary": 4, "grammar": 4, "task": 4}\n```'
    scores = parse_rubric_response(content)
    assert scores.mock_score == 9


def test_parse_rubric_clamps_and_truncates() -> None:
    """维度超界截断到 0-4；建议/升级截断到 3/2 条。"""
    content = json.dumps(
        {
            "fluency": 9,
            "vocabulary": -1,
            "grammar": "3",
            "task": 2,
            "advice": ["a", "b", "c", "d", "e"],
            "upgrades": ["u1", "u2", "u3"],
        }
    )
    scores = parse_rubric_response(content)
    assert scores.fluency == DIMENSION_MAX
    assert scores.vocabulary == 0
    assert scores.grammar == 3
    assert len(scores.advice) == MAX_ADVICE
    assert len(scores.upgrades) == MAX_UPGRADES


def test_parse_rubric_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="JSON"):
        parse_rubric_response("I think the student did well.")


def test_parse_rubric_rejects_empty_object() -> None:
    """核心回归：空对象不得产出真实零分（PRD US-08 绝不出 0 分）。"""
    with pytest.raises(RubricParseError):
        parse_rubric_response("{}")


def test_parse_rubric_rejects_advice_only_object() -> None:
    content = json.dumps({"advice": ["多说完整句"], "upgrades": []})
    with pytest.raises(RubricParseError, match="fluency"):
        parse_rubric_response(content)


def test_parse_rubric_rejects_partial_dimensions() -> None:
    content = json.dumps({"fluency": 3, "vocabulary": 2, "grammar": 2})
    with pytest.raises(RubricParseError, match="task"):
        parse_rubric_response(content)


@pytest.mark.parametrize(
    "bad_value",
    [None, True, False, [3], {"v": 3}, "abc", "NaN", "Infinity"],
)
def test_parse_rubric_rejects_bad_dimension_values(bad_value: object) -> None:
    content = json.dumps(
        {
            "fluency": bad_value,
            "vocabulary": 2,
            "grammar": 2,
            "task": 2,
        }
    )
    with pytest.raises(RubricParseError, match="fluency"):
        parse_rubric_response(content)


def test_parse_rubric_rejects_json_nan_and_infinity_literals() -> None:
    """json.loads 默认接受 NaN/Infinity 字面量，必须拦下（int(NaN) 会 ValueError）。"""
    with pytest.raises(RubricParseError):
        parse_rubric_response(
            '{"fluency": NaN, "vocabulary": 1, "grammar": 1, "task": 1}'
        )
    with pytest.raises(RubricParseError):
        parse_rubric_response(
            '{"fluency": 1, "vocabulary": Infinity, "grammar": 1, "task": 1}'
        )


def test_parse_rubric_rejects_non_object_json() -> None:
    with pytest.raises(RubricParseError):
        parse_rubric_response("[1, 2, 3]")
    with pytest.raises(RubricParseError):
        parse_rubric_response('"just a string"')


def test_parse_rubric_rejects_broken_json_with_braces() -> None:
    with pytest.raises(RubricParseError, match="合法 JSON"):
        parse_rubric_response('{"fluency": 3, "vocabulary": }')


def test_parse_rubric_accepts_legitimate_all_zero() -> None:
    """合法四维全 0 必须保留（真说过但确实差），不能因收紧误伤。"""
    content = json.dumps({"fluency": 0, "vocabulary": 0, "grammar": 0, "task": 0})
    scores = parse_rubric_response(content)
    assert scores.mock_score == 0
    assert scores.advice == []
    assert scores.upgrades == []


def test_parse_rubric_rejects_string_advice_not_per_char() -> None:
    """advice 传字符串不得被逐字符当建议（旧行为的静默垃圾）。"""
    content = json.dumps(
        {
            "fluency": 2,
            "vocabulary": 2,
            "grammar": 2,
            "task": 2,
            "advice": "很好",
        }
    )
    with pytest.raises(RubricParseError, match="advice"):
        parse_rubric_response(content)


def test_parse_rubric_rejects_non_string_advice_element() -> None:
    content = json.dumps(
        {
            "fluency": 2,
            "vocabulary": 2,
            "grammar": 2,
            "task": 2,
            "upgrades": [{"from": "a", "to": "b"}],
        }
    )
    with pytest.raises(RubricParseError, match="upgrades"):
        parse_rubric_response(content)


def test_parse_rubric_drops_blank_advice_entries() -> None:
    content = json.dumps(
        {
            "fluency": 2,
            "vocabulary": 2,
            "grammar": 2,
            "task": 2,
            "advice": ["有效建议", "", "   "],
        }
    )
    scores = parse_rubric_response(content)
    assert scores.advice == ["有效建议"]


def test_user_prompt_contains_inputs() -> None:
    prompt = build_rubric_user_prompt("Do you like cats?", "B1", "i like cats")
    assert "Do you like cats?" in prompt
    assert "B1" in prompt
    assert "i like cats" in prompt


def test_ark_rubric_scorer_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/v3/chat/completions"
        assert body["model"] == "doubao-seed-2-0-lite-260428"
        assert body["thinking"] == {"type": "disabled"}
        assert body["max_tokens"] == 2048
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        content = json.dumps({"fluency": 2, "vocabulary": 2, "grammar": 1, "task": 2})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    scorer = ArkRubricScorer(
        api_key="key",
        model="doubao-seed-2-0-lite-260428",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    scores = scorer.score("Do you like cats?", "B1", "yes i like")
    assert scores.mock_score == map_to_mock_score(7)


def test_ark_rubric_scorer_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    scorer = ArkRubricScorer(
        api_key="key",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match="429"):
        scorer.score("q", "B1", "t")


def test_ark_rubric_scorer_requires_key() -> None:
    scorer = ArkRubricScorer(api_key="", model="m")
    with pytest.raises(ValueError, match="ARK_API_KEY"):
        scorer.score("q", "B1", "t")


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _make_done_attempt_with_pending_rubric(db: Session) -> Attempt:
    attempt = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        audio_path="/tmp/nonexistent.webm",
        audio_mime="audio/webm",
        duration_s=6.0,
        engine="ark",
        status=AttemptStatus.DONE,
        transcript="i like dogs",
        rubric={"status": "pending"},
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def _mock_llm(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    """让 worker 的 _score_rubric 走 MockTransport：HTTP 200 + 指定 content。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ARK_API_KEY", "test-key")
    monkeypatch.setattr(
        rubric_module,
        "_shared_client",
        httpx.Client(transport=httpx.MockTransport(lambda r: _chat_response(content))),
    )


class TestWorkerRubricDegradation:
    """worker 持久化路径：坏输出 → unavailable；合法 0 分 → 真实 0 可区分。"""

    def test_bad_json_persists_unavailable(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempt = _make_done_attempt_with_pending_rubric(db)
        try:
            _mock_llm(monkeypatch, "{}")
            worker._complete_detail(attempt.id, "Do you like cats?", "B1", "i like")
            db.refresh(attempt)
            assert attempt.rubric == {"status": "unavailable"}
        finally:
            db.delete(attempt)
            db.commit()

    def test_advice_only_response_persists_unavailable(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempt = _make_done_attempt_with_pending_rubric(db)
        try:
            _mock_llm(monkeypatch, json.dumps({"advice": ["多说完整句"]}))
            worker._complete_detail(attempt.id, "Do you like cats?", "B1", "i like")
            db.refresh(attempt)
            assert attempt.rubric == {"status": "unavailable"}
        finally:
            db.delete(attempt)
            db.commit()

    def test_legitimate_zero_scores_persist(
        self, db: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempt = _make_done_attempt_with_pending_rubric(db)
        try:
            _mock_llm(
                monkeypatch,
                json.dumps({"fluency": 0, "vocabulary": 0, "grammar": 0, "task": 0}),
            )
            worker._complete_detail(attempt.id, "Do you like cats?", "B1", "i like")
            db.refresh(attempt)
            assert attempt.rubric is not None
            assert attempt.rubric.get("status") is None  # 正常出分不带 status
            assert attempt.rubric.get("mock_score") == 0
            assert attempt.rubric.get("fluency") == 0
        finally:
            db.delete(attempt)
            db.commit()
