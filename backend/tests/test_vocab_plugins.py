"""玩法注册表测试（#618 第二批）：六题型全注册 / 载荷与判分不变 / 可扩展。"""

from types import SimpleNamespace
from typing import cast

from app.models.vocabulary.words import VOCAB_PROMPT_TYPES
from app.services import vocab_plugins as reg
from app.services.vocabulary_prompt_types import attach_prompt_payloads


def _word(i: int, *, example: str | None = None, morph: list | None = None):
    return SimpleNamespace(
        id=f"w{i}",
        headword=f"word{i}",
        meaning_zh=f"词{i}",
        part_of_speech="n.",
        example_en=example,
        morphology=morph,
        audio_url=None,
    )


def test_every_prompt_type_registered_in_original_order() -> None:
    """六个题型全部注册，顺序与 TEACHER 勾选顺序一致。"""
    assert [p.key for p in reg.all_plugins()] == list(VOCAB_PROMPT_TYPES)


def test_dimensions_cover_the_four_skills() -> None:
    assert set(reg.dimensions()) == {
        "spelling",
        "recognition",
        "context",
        "morphology",
    }


def test_judge_choice_and_spelling_same_as_before() -> None:
    """判分口径不变：选择题比词条 ID，拼写题比快照可接受拼写。"""
    choice_snapshot: dict[str, object] = {
        "word_id": "w1",
        "headword": "apple",
        "accepted_spellings": [],
        "prompt_types": ["en_zh"],
    }
    assert reg.judge_answer("en_zh", "W1", choice_snapshot) is True
    assert reg.judge_answer("en_zh", "apple", choice_snapshot) is False

    spelling_snapshot: dict[str, object] = {
        "word_id": "w2",
        "headword": "colour",
        "accepted_spellings": ["color"],
        "prompt_types": ["meaning"],
    }
    assert reg.judge_answer("meaning", " Color ", spelling_snapshot) is True
    assert reg.judge_answer("meaning", "colours", spelling_snapshot) is False


def test_roots_judged_by_assembled_spelling() -> None:
    """词根题答的是拼回的词形，不是词条 ID（与既有口径一致）。"""
    snapshot: dict[str, object] = {
        "word_id": "w9",
        "headword": "teacher",
        "accepted_spellings": [],
        "prompt_types": ["roots"],
        "morph_segments": [],
    }
    assert reg.judge_answer("roots", "Teacher", snapshot) is True
    assert reg.judge_answer("roots", "w9", snapshot) is False


def test_letters_payload_scrambles_deterministically() -> None:
    """字母重排：字母一个不少、顺序不为原词、同词两次一致。"""
    snapshot: dict[str, object] = {"headword": "teacher", "prompt_types": ["letters"]}
    attach_prompt_payloads([snapshot], [_word(1, example=None)])
    # 用真实词形覆盖 headword，payload 才会按它打乱
    snapshot["headword"] = "teacher"
    reg.require_plugin("letters").payload(0, _word(1), [], snapshot)
    pool = cast("list[str]", snapshot["letters_pool"])
    assert sorted(pool) == sorted("teacher")
    assert "".join(pool).casefold() != "teacher"

    second: dict[str, object] = {"headword": "teacher"}
    reg.require_plugin("letters").payload(0, _word(1), [], second)
    assert second["letters_pool"] == pool


def test_letters_supports_only_plain_words() -> None:
    plugin = reg.require_plugin("letters")
    assert plugin.supports(SimpleNamespace(headword="teacher")) is True
    assert plugin.supports(SimpleNamespace(headword="ab")) is False
    assert plugin.supports(SimpleNamespace(headword="two words")) is False
    assert plugin.supports(SimpleNamespace(headword="前缀")) is False


def test_letters_judged_by_spelling() -> None:
    snapshot: dict[str, object] = {
        "word_id": "w3",
        "headword": "teacher",
        "accepted_spellings": [],
        "prompt_types": ["letters"],
    }
    assert reg.judge_answer("letters", "Teacher", snapshot) is True
    assert reg.judge_answer("letters", "teach", snapshot) is False


def test_unknown_prompt_type_judges_false() -> None:
    """没注册的题型不再静默按拼写比对（避免误判对）。"""
    assert reg.judge_answer("not_registered", "apple", {"headword": "apple"}) is False


def test_payloads_unchanged_for_choice_cloze_roots() -> None:
    words = [_word(i, example=f"We use word{i} daily.") for i in range(1, 5)]
    morph: list[dict[str, str]] = [
        {"text": "un", "gloss": "not", "kind": "prefix"},
        {"text": "word4", "gloss": "root", "kind": "root"},
    ]
    words[3].morphology = morph

    snapshots: list[dict[str, object]] = [
        {"headword": "word1", "meaning_zh": "词1", "prompt_types": ["meaning"]},
        {
            "headword": "word2",
            "meaning_zh": "词2",
            "example_en": "We use word2 daily.",
            "prompt_types": ["cloze"],
        },
        {"headword": "word4", "meaning_zh": "词4", "prompt_types": ["roots"]},
    ]
    attach_prompt_payloads(snapshots, words)

    choices = cast("list[dict[str, object]]", snapshots[0]["choices"])
    assert len(choices) == 4
    assert any(opt["word_id"] == "w1" for opt in choices), "正确项必须在内"
    assert "__" in str(snapshots[1]["cloze_sentence"]) or "___" in str(
        snapshots[1]["cloze_sentence"]
    )
    assert snapshots[2]["morph_segments"], "词根题必须固化语素块"


def test_new_plugin_registers_without_core_changes(monkeypatch) -> None:
    """新增玩法只需一条注册项：判分立即生效，不改核心分派代码。"""
    demo = reg.PromptPlugin(
        key="demo_digits",
        label_zh="数字回填",
        label_en="Digits",
        dimension="spelling",
        requires=(reg.REQUIRE_WORD,),
        supports=lambda _word: True,
        payload=lambda *_args: None,
        judge=lambda answer, _snapshot, _key: answer.strip() == "42",
    )
    monkeypatch.setattr(reg, "_REGISTRY", {**reg._REGISTRY, demo.key: demo})
    assert reg.judge_answer("demo_digits", "42", {}) is True
    assert reg.judge_answer("demo_digits", "41", {}) is False
    assert demo.key in [p.key for p in reg.all_plugins()]
