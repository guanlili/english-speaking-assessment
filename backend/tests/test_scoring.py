"""启发式评分与 ASR 提供方的单元测试（纯函数，不依赖数据库）。"""

import base64

import httpx
import pytest

from app.scoring.asr import (
    ArkResponsesAsr,
    MockAsr,
    build_ark_payload,
    parse_ark_response,
)
from app.scoring.base import ScoringError
from app.scoring.heuristic import (
    SILENCE_ADVICE,
    completeness_score,
    fluency_score,
    score_read_aloud,
    tokenize,
)

REFERENCE = (
    "Many students in our class have pets at home. "
    "Some prefer cats because they are quiet and independent. "
    "I prefer dogs. Dogs are friendly and loyal."
)


def test_tokenize_keeps_apostrophes() -> None:
    assert tokenize("Don't stop, it's easy!") == ["don't", "stop", "it's", "easy"]


def test_completeness_full_match_is_100() -> None:
    ref = tokenize(REFERENCE)
    assert completeness_score(ref, ref) == 100


def test_completeness_half_read_is_about_50() -> None:
    ref = ["a"] * 10 + ["b"] * 10
    assert completeness_score(ref[:10], ref) == 50


def test_completeness_repeats_dont_inflate() -> None:
    # 参考文本 3 个词，只命中 1 个且重复念 4 遍 → 33 分
    assert completeness_score(["a", "a", "a", "a"], ["a", "b", "c"]) == 33


def test_fluency_target_speed_is_100() -> None:
    assert fluency_score(25, 10.0) == 100  # 2.5 词/秒


def test_fluency_very_slow_is_low() -> None:
    assert fluency_score(25, 50.0) == 0  # 0.5 词/秒


def test_fluency_silence_is_zero() -> None:
    assert fluency_score(0, 10.0) == 0


def test_advice_mentions_missed_words() -> None:
    transcript = "many students in our class have pets at home i prefer dogs"
    scores = score_read_aloud(transcript, REFERENCE, duration_s=15.0)
    assert len(scores.advice) <= 2
    assert any("cats" in a or "friendly" in a for a in scores.advice)


def test_advice_silence() -> None:
    scores = score_read_aloud("", REFERENCE, duration_s=10.0)
    assert scores.advice == [SILENCE_ADVICE]
    assert scores.completeness == 0
    assert scores.fluency == 0


def test_score_read_aloud_perfect_transcript() -> None:
    scores = score_read_aloud(REFERENCE, REFERENCE, duration_s=30.0)
    assert scores.completeness == 100
    assert scores.overall >= 60


def test_mock_asr_is_deterministic() -> None:
    asr = MockAsr()
    assert asr.transcribe(b"x", "audio/webm") == asr.transcribe(b"x", "audio/webm")
    assert asr.name == "mock"


def test_build_ark_payload_inlines_base64_audio() -> None:
    payload = build_ark_payload("m-1", b"abc", "audio/webm")
    content = payload["input"][0]["content"][0]
    assert content["type"] == "input_audio"
    expected = f"data:audio/webm;base64,{base64.b64encode(b'abc').decode()}"
    assert content["audio_url"] == expected
    assert payload["model"] == "m-1"
    assert "transcript" in payload["instructions"].lower()


def test_parse_ark_response_joins_output_text() -> None:
    data = {
        "output": [
            {
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "Many students "},
                    {"type": "output_text", "text": "have pets."},
                ],
            }
        ]
    }
    assert parse_ark_response(data) == "Many students have pets."
    assert parse_ark_response({}) == ""


def test_ark_asr_success_via_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/responses"
        assert request.headers["authorization"] == "Bearer key-1"
        return httpx.Response(
            200,
            json={
                "output": [
                    {"content": [{"type": "output_text", "text": "i prefer dogs"}]}
                ]
            },
        )

    asr = ArkResponsesAsr(
        api_key="key-1",
        model="m",
        base_url="https://ark.example/api/v3",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert asr.transcribe(b"audio", "audio/webm") == "i prefer dogs"


def test_ark_asr_model_not_found_maps_to_scoring_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"type": "model_not_found", "message": "nope"}}
        )

    asr = ArkResponsesAsr(
        api_key="key-1",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ScoringError, match="404"):
        asr.transcribe(b"audio", "audio/webm")


def test_ark_asr_requires_api_key() -> None:
    asr = ArkResponsesAsr(api_key="", model="m")
    with pytest.raises(ScoringError, match="ARK_API_KEY"):
        asr.transcribe(b"audio", "audio/webm")


def test_open_response_advice_is_full_sentence() -> None:
    """回归：开放题建议必须是完整句子，不是被切片的单个字符。"""
    from app.scoring.heuristic import score_open_response

    scores = score_open_response("i like dogs because they are friendly", 8.0)
    assert len(scores.advice) == 1
    assert len(scores.advice[0]) >= 10

    silent = score_open_response("", 5.0)
    assert silent.overall == 0
    assert silent.advice == [SILENCE_ADVICE]


def test_open_response_scores_range() -> None:
    from app.scoring.heuristic import score_open_response

    scores = score_open_response("word " * 20, 10.0)
    assert 0 <= scores.fluency <= 100
    assert 0 <= scores.overall <= 100
