"""US-08 rubric 评分器单元测试（纯函数 + MockTransport）。"""

import json

import httpx
import pytest

from app.scoring.rubric import (
    DIMENSION_MAX,
    MAX_ADVICE,
    MAX_UPGRADES,
    RUBRIC_TO_SCORE,
    ArkRubricScorer,
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


def test_user_prompt_contains_inputs() -> None:
    prompt = build_rubric_user_prompt("Do you like cats?", "B1", "i like cats")
    assert "Do you like cats?" in prompt
    assert "B1" in prompt
    assert "i like cats" in prompt


def test_ark_rubric_scorer_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/v3/chat/completions"
        assert body["model"] == "rubric-model"
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        content = json.dumps({"fluency": 2, "vocabulary": 2, "grammar": 1, "task": 2})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    scorer = ArkRubricScorer(
        api_key="key",
        model="rubric-model",
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
