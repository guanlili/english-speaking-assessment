"""玩法注册表：把「题型」从散落在各处的分支收成一份声明（#618 第二批）。

每个玩法声明六件事，新增玩法只加一条注册项：

1. ``key``：题面/判分/统计里用的稳定标识（与 ``VOCAB_PROMPT_TYPES`` 对齐）；
2. ``dimension``：能力维度（拼写/认读/语境/词法…），每日挑战按维度挑不同玩法；
3. ``requires``：素材依赖（词条本身 / 音频 / 例句 / 词根），教师勾选与降级判断都读它；
4. ``supports``：单条词能否出这种题；
5. ``payload``：快照里要固化的题面载荷（选项、挖空句、字母块…）；
6. ``judge``：判分。

行为一律**委托现有实现**：注册表负责「声明与分派」，具体构造和判分仍在
``vocabulary_prompt_types`` / ``vocabulary`` 里，所以现有 6 题型的快照格式、
判分结果、统计口径不会因为这次重构而变（有回归测试锁住）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models.vocabulary.words import VOCAB_PROMPT_TYPES

# 素材依赖：UI/发布校验按这些标签决定「缺什么就不能出题」
REQUIRE_WORD = "word"  # 词条本身（拼写/释义）
REQUIRE_AUDIO = "audio"  # 音频
REQUIRE_EXAMPLE = "example"  # 例句（可挖空）
REQUIRE_MORPHOLOGY = "morphology"  # 词根/语素

DIMENSION_LABELS: dict[str, tuple[str, str]] = {
    "spelling": ("拼写", "Spelling"),
    "recognition": ("认读", "Recognition"),
    "context": ("语境", "Context"),
    "morphology": ("词法", "Morphology"),
}

REQUIRE_LABELS: dict[str, str] = {
    REQUIRE_WORD: "词条拼写与释义",
    REQUIRE_AUDIO: "发音音频",
    REQUIRE_EXAMPLE: "可挖空的英文例句",
    REQUIRE_MORPHOLOGY: "词根拆解（至少两个语素）",
}


@dataclass(frozen=True)
class PromptPlugin:
    """一个玩法的完整声明。函数字段一律是「薄委托」，不在这里写业务逻辑。"""

    key: str
    label_zh: str
    label_en: str
    dimension: str
    requires: tuple[str, ...]
    supports: Callable[[Any], bool]
    payload: Callable[[int, Any, list[Any], dict[str, object]], None]
    judge: Callable[[str, dict[str, object], str], bool]
    renderer: str = "text_input"


_REGISTRY: dict[str, PromptPlugin] = {}


def register(plugin: PromptPlugin) -> PromptPlugin:
    """注册玩法：key 重复直接报错，避免两份声明给出两套口径。"""
    if plugin.key in _REGISTRY:
        raise ValueError(f"玩法 key 重复注册：{plugin.key}")
    _REGISTRY[plugin.key] = plugin
    return plugin


def get_plugin(key: str) -> PromptPlugin | None:
    return _REGISTRY.get(key)


def require_plugin(key: str) -> PromptPlugin:
    plugin = _REGISTRY.get(key)
    if plugin is None:
        raise ValueError(f"未注册的玩法：{key}")
    return plugin


def all_plugins() -> list[PromptPlugin]:
    """按 ``VOCAB_PROMPT_TYPES`` 的既有顺序返回（前端/教师勾选顺序不变）。"""
    ordered = [p for key in VOCAB_PROMPT_TYPES if (p := _REGISTRY.get(key))]
    extra = [p for key, p in _REGISTRY.items() if key not in VOCAB_PROMPT_TYPES]
    extra.sort(key=lambda p: p.key)
    return ordered + extra


def plugins_by_dimension(dimension: str) -> list[PromptPlugin]:
    return [p for p in all_plugins() if p.dimension == dimension]


def dimensions() -> list[str]:
    """已注册的能力维度（按首次出现顺序，去重）。"""
    seen: list[str] = []
    for plugin in all_plugins():
        if plugin.dimension not in seen:
            seen.append(plugin.dimension)
    return seen


def judge_answer(
    prompt_type: str, answer: str, snapshot_item: dict[str, object]
) -> bool:
    """判分统一入口：未注册的题型一律判错（不再静默走拼写比对）。"""
    plugin = get_plugin(prompt_type)
    if plugin is None:
        return False
    return plugin.judge(answer, snapshot_item, prompt_type)


# ── 现有 6 题型的注册项（行为委托给既有实现） ─────────────────────


def _supports_always(_word: Any) -> bool:
    return True


def _supports_audio(word: Any) -> bool:
    from app.services import vocabulary_prompt_types as pt

    return pt.word_supports_prompt_type(word, "audio")


def _supports_cloze(word: Any) -> bool:
    from app.services import vocabulary_prompt_types as pt

    return pt.word_supports_prompt_type(word, "cloze")


def _supports_roots(word: Any) -> bool:
    from app.services import vocabulary_prompt_types as pt

    return pt.word_supports_prompt_type(word, "roots")


def _payload_none(
    _idx: int, _word: Any, _words: list[Any], _snapshot: dict[str, object]
) -> None:
    return None


def _payload_choices(
    idx: int, word: Any, words: list[Any], snapshot: dict[str, object]
) -> None:
    from app.services import vocabulary_prompt_types as pt

    snapshot["choices"] = pt._build_choices(idx, word, words)


def _payload_cloze(
    _idx: int, _word: Any, _words: list[Any], snapshot: dict[str, object]
) -> None:
    from app.services.vocabulary_prompt_types import build_cloze_sentence

    example = snapshot.get("example_en")
    snapshot["cloze_sentence"] = build_cloze_sentence(
        str(snapshot["headword"]), example if isinstance(example, str) else None
    )


def _payload_roots(
    _idx: int, word: Any, _words: list[Any], snapshot: dict[str, object]
) -> None:
    from app.services import vocabulary_prompt_types as pt

    snapshot["morph_segments"] = pt._build_morph_segments(word)


def _judge_choice(answer: str, snapshot: dict[str, object], _key: str) -> bool:
    from app.services.vocabulary_prompt_types import choice_answer_matches

    return choice_answer_matches(answer, snapshot)


def _judge_spelling(answer: str, snapshot: dict[str, object], _key: str) -> bool:
    from app.services.vocabulary import check_spelling

    return check_spelling(answer, snapshot)


for _plugin in (
    PromptPlugin(
        key="meaning",
        label_zh="看词写义",
        label_en="Meaning",
        dimension="spelling",
        requires=(REQUIRE_WORD,),
        supports=_supports_always,
        payload=_payload_choices,
        judge=_judge_spelling,
    ),
    PromptPlugin(
        key="audio",
        label_zh="听音拼写",
        label_en="Audio spelling",
        dimension="spelling",
        requires=(REQUIRE_WORD, REQUIRE_AUDIO),
        supports=_supports_audio,
        payload=_payload_none,
        judge=_judge_spelling,
    ),
    PromptPlugin(
        key="en_zh",
        label_zh="英选中",
        label_en="EN → ZH",
        dimension="recognition",
        requires=(REQUIRE_WORD,),
        supports=_supports_always,
        payload=_payload_choices,
        judge=_judge_choice,
    ),
    PromptPlugin(
        key="zh_en",
        label_zh="中选英",
        label_en="ZH → EN",
        dimension="recognition",
        requires=(REQUIRE_WORD,),
        supports=_supports_always,
        payload=_payload_choices,
        judge=_judge_choice,
    ),
    PromptPlugin(
        key="cloze",
        label_zh="语境填词",
        label_en="Cloze",
        dimension="context",
        requires=(REQUIRE_WORD, REQUIRE_EXAMPLE),
        supports=_supports_cloze,
        payload=_payload_cloze,
        judge=_judge_spelling,
    ),
    PromptPlugin(
        key="roots",
        label_zh="词根组词",
        label_en="Word roots",
        dimension="morphology",
        requires=(REQUIRE_WORD, REQUIRE_MORPHOLOGY),
        supports=_supports_roots,
        payload=_payload_roots,
        judge=_judge_spelling,
    ),
):
    register(_plugin)


__all__ = [
    "DIMENSION_LABELS",
    "PromptPlugin",
    "REQUIRE_AUDIO",
    "REQUIRE_EXAMPLE",
    "REQUIRE_LABELS",
    "REQUIRE_MORPHOLOGY",
    "REQUIRE_WORD",
    "all_plugins",
    "dimensions",
    "get_plugin",
    "judge_answer",
    "plugins_by_dimension",
    "register",
    "require_plugin",
]
