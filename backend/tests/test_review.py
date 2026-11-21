"""问答逐句批改单元测试：切句偏移、严格解析、定位降级与方舟调用。"""

import json

import httpx
import pytest

from app.scoring.review import (
    MAX_REVIEW_ISSUES,
    MAX_REVIEW_SENTENCES,
    REVIEW_PROMPT_VERSION,
    ArkSentenceReviewer,
    ReviewParseError,
    build_review_user_prompt,
    parse_review_response,
    split_sentences,
)


def test_split_sentences_keeps_original_offsets() -> None:
    text = "I very like play basketball. It are fun! Do you like it?"
    spans, truncated = split_sentences(text)
    assert truncated is False
    assert [span.text for span in spans] == [
        "I very like play basketball.",
        "It are fun!",
        "Do you like it?",
    ]
    for span in spans:
        assert text[span.start : span.end] == span.text
        assert span.index == spans.index(span)


def test_split_sentences_truncates_to_limit() -> None:
    text = " ".join(f"Sentence number {i}." for i in range(14))
    spans, truncated = split_sentences(text)
    assert truncated is True
    assert len(spans) == MAX_REVIEW_SENTENCES
    assert spans[0].index == 0
    assert spans[-1].index == MAX_REVIEW_SENTENCES - 1


def test_split_sentences_chunks_long_unpunctuated_text() -> None:
    text = " ".join(f"word{i}" for i in range(60))
    spans, _ = split_sentences(text)
    assert len(spans) == 3
    assert spans[0].text.startswith("word0")
    assert spans[1].text.startswith("word22")


def test_parse_review_locates_spans_and_marks_clean() -> None:
    spans, _ = split_sentences("I very like play basketball. It is fun.")
    content = json.dumps(
        {
            "sentences": [
                {
                    "index": 0,
                    "clean": False,
                    "corrected": "I really like playing basketball.",
                    "issues": [
                        {
                            "type": "grammar",
                            "span": "very",
                            "suggestion": "really",
                            "why_zh": "very 不能直接修饰动词",
                            "why_en": "Use 'really' before a verb.",
                        },
                        {
                            "type": "expression",
                            "span": "play",
                            "suggestion": "playing",
                            "why_zh": "like 后面接动名词",
                            "why_en": "Use the -ing form after 'like'.",
                        },
                    ],
                },
                {"index": 1, "clean": True, "issues": []},
            ]
        }
    )
    review = parse_review_response(content, spans, model="test-model")
    assert review["status"] == "done"
    assert review["prompt_version"] == REVIEW_PROMPT_VERSION
    sentence = review["sentences"][0]
    assert sentence["clean"] is False
    assert sentence["corrected"] == "I really like playing basketball."
    assert sentence["issues"][0]["start"] == 2
    assert sentence["issues"][0]["end"] == 6
    assert sentence["issues"][1]["start"] == 12
    assert review["sentences"][1]["clean"] is True
    assert review["sentences"][1]["issues"] == []
    assert review["sentences"][1]["pronunciation"] == {"status": "unavailable"}
    assert "1 处语法" in review["summary"]["zh"]
    assert "1 expression" in review["summary"]["en"]


def test_parse_review_degrades_unlocatable_span_to_whole_sentence() -> None:
    spans, _ = split_sentences("I very like it.")
    content = json.dumps(
        {
            "sentences": [
                {
                    "index": 0,
                    "issues": [
                        {
                            "type": "grammar",
                            "span": "not in sentence",
                            "suggestion": "fix",
                            "why_zh": "说明",
                            "why_en": "why",
                        }
                    ],
                }
            ]
        }
    )
    review = parse_review_response(content, spans)
    issue = review["sentences"][0]["issues"][0]
    assert issue["span"] == "I very like it."
    assert issue["start"] == 0
    assert issue["end"] == len("I very like it.")


def test_parse_review_drops_unknown_types_and_caps_issues() -> None:
    spans, _ = split_sentences("I very like it.")
    issues = [
        {"type": "pronunciation", "span": "very", "suggestion": "x"},
        *[
            {
                "type": "grammar",
                "span": "very",
                "suggestion": f"fix{i}",
                "why_zh": "说明",
                "why_en": "why",
            }
            for i in range(MAX_REVIEW_ISSUES + 2)
        ],
    ]
    content = json.dumps({"sentences": [{"index": 0, "issues": issues}]})
    review = parse_review_response(content, spans)
    assert len(review["sentences"][0]["issues"]) == MAX_REVIEW_ISSUES
    assert all(issue["type"] == "grammar" for issue in review["sentences"][0]["issues"])


def test_parse_review_pads_missing_sentences_as_clean() -> None:
    spans, _ = split_sentences("One. Two.")
    content = json.dumps(
        {
            "sentences": [
                {
                    "index": 0,
                    "issues": [
                        {
                            "type": "grammar",
                            "span": "One",
                            "suggestion": "Once",
                            "why_zh": "说明",
                            "why_en": "why",
                        }
                    ],
                }
            ]
        }
    )
    review = parse_review_response(content, spans)
    assert review["sentences"][1]["clean"] is True


def test_parse_review_rejects_non_json() -> None:
    spans, _ = split_sentences("I like it.")
    with pytest.raises(ReviewParseError, match="JSON"):
        parse_review_response("I think this is fine.", spans)


def test_parse_review_rejects_missing_sentences_list() -> None:
    spans, _ = split_sentences("I like it.")
    with pytest.raises(ReviewParseError, match="sentences"):
        parse_review_response("{}", spans)


def test_review_prompt_lists_numbered_sentences() -> None:
    spans, _ = split_sentences("I very like it. It are fun.")
    prompt = build_review_user_prompt("Do you like it?", spans)
    assert "Do you like it?" in prompt
    assert '[0] "I very like it."' in prompt
    assert '[1] "It are fun."' in prompt


def test_ark_sentence_reviewer_calls_chat_and_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/v3/chat/completions"
        assert body["model"] == "doubao-seed-2-0-lite-260428"
        assert body["thinking"] == {"type": "disabled"}
        assert len(body["messages"]) == 2
        content = json.dumps(
            {
                "sentences": [
                    {
                        "index": 0,
                        "issues": [
                            {
                                "type": "grammar",
                                "span": "very",
                                "suggestion": "really",
                                "why_zh": "very 不能直接修饰动词",
                                "why_en": "Use 'really' before a verb.",
                            }
                        ],
                    }
                ]
            }
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    reviewer = ArkSentenceReviewer(
        api_key="key",
        model="doubao-seed-2-0-lite-260428",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    review = reviewer.review("Do you like it?", "I very like it.")
    assert review["status"] == "done"
    assert review["model"] == "doubao-seed-2-0-lite-260428"
    assert review["sentences"][0]["issues"][0]["suggestion"] == "really"
