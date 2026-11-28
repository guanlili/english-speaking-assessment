"""词汇多样出题：题型内容准备、快照载荷与判分（第一批四类真实玩法）。

设计口径（与 issue #517 V2 一致）：

- 四类玩法全部真实判分：英译中 / 中译英 = 四选一，按所选词条 ID 判定；
  语境填空 / 词根拼装 = 拼写题，复用 accepted_spellings 判定。
- 内容不足即不出该题：词条没有可挖空例句就不能出语境填空，词法拆解
  拼不回原词就不能出词根拼装。发布时校验「至少一个词可出」，避免
  教师勾了题型却看到空题。
- 选项与语素块在发布时固化进快照：之后改词库不影响已发任务，同一任务
  每次打开选项顺序与内容一致。
- 演示词料由 AI 起草、按待审核处理；本模块只负责「能不能出题」，不代表
  教学准确性已获学校老师验收。
"""

import hashlib
import re
import uuid
from typing import Any

from fastapi import HTTPException

from app.models.vocabulary.words import (
    CHOICE_PROMPT_TYPES,
    CONTENT_PROMPT_TYPES,
    VOCAB_PROMPT_TYPES,
)

LEGACY_PROMPT_TYPES = ("meaning", "audio")
MIN_CHOICE_WORDS = 4  # 正确项 + 3 个干扰项；不足四词不出选择题
MORPH_DECOY_POOL = ("re", "tion", "un", "pre", "able", "ly", "ness", "ment")
MORPH_KINDS = ("prefix", "root", "suffix")

# ── 认读 / 拼写能力维度（FSRS 复习状态按维度分离，2026-11-22 第二批）─────
# 认读 = 选择题类（看词/看义选对应项，不输入词形）；
# 拼写 = 输入词形类（看义/听音/挖空/语素拼装）。
RECOGNITION_PROMPT_TYPES = CHOICE_PROMPT_TYPES
SPELLING_PROMPT_TYPES = ("meaning", "audio", "cloze", "roots")
CAPABILITY_RECOGNITION = "recognition"
CAPABILITY_SPELLING = "spelling"


def capability_of_prompt_type(prompt_type: str) -> str:
    """题型 → 能力维度；未知题型按拼写兜底（输入词形口径）。"""
    if prompt_type in CHOICE_PROMPT_TYPES:
        return CAPABILITY_RECOGNITION
    return CAPABILITY_SPELLING


def prompt_types_for_capability(capability: str, *, has_audio: bool) -> list[str]:
    """能力维度 → 复习轮建议题型（快照分配用）。

    认读固定英译中（不依赖标准音/例句素材）；拼写有标准音时听音+看义，
    否则只看义。返回顺序即快照优先顺序。
    """
    if capability == CAPABILITY_RECOGNITION:
        return ["en_zh"]
    return ["audio", "meaning"] if has_audio else ["meaning"]


# ── 词条素材 ───────────────────────────────────────────────────────


def normalize_morphology(raw: Any) -> list[dict[str, str]]:
    """把词法拆解清洗成 [{text, gloss, kind}]；不合法返回空列表。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, str]] = []
    for part in raw:
        if not isinstance(part, dict):
            return []
        text = str(part.get("text") or "").strip()
        gloss = str(part.get("gloss") or "").strip()
        kind = str(part.get("kind") or "root").strip().lower()
        if not text or not gloss:
            return []
        if kind not in MORPH_KINDS:
            kind = "root"
        cleaned.append({"text": text, "gloss": gloss, "kind": kind})
    return cleaned


def morphology_assembles(headword: str, morphology: list[dict[str, str]]) -> bool:
    """拆解块拼回来必须等于词形，否则语素块教的是另一个词。"""
    if not morphology:
        return False
    joined = "".join(seg["text"] for seg in morphology)
    return joined.casefold() == headword.casefold()


def build_cloze_sentence(headword: str, example_en: str | None) -> str | None:
    """把例句里的目标词挖成 ____；例句不含原形则不出语境填空题。

    只接受完整词形（词边界 + 忽略大小写），不做词形还原：把 studies
    当 study 处理需要词法分析，出错会把别的词当答案，宁可不出题。
    """
    if not example_en:
        return None
    pattern = re.compile(rf"\b{re.escape(headword)}\b", re.IGNORECASE)
    if not pattern.search(example_en):
        return None
    sentence = pattern.sub("____", example_en, count=1)
    return sentence


def word_supports_prompt_type(word: Any, prompt_type: str) -> bool:
    """单条词能否出这种题（只判断素材，与任务上下文无关）。"""
    if prompt_type in ("meaning", "en_zh", "zh_en"):
        return True
    if prompt_type == "audio":
        return bool(getattr(word, "audio_url", None))
    if prompt_type == "cloze":
        return (
            build_cloze_sentence(
                str(getattr(word, "headword", "")),
                getattr(word, "example_en", None),
            )
            is not None
        )
    if prompt_type == "roots":
        morphology = normalize_morphology(getattr(word, "morphology", None))
        headword = str(getattr(word, "headword", ""))
        return morphology_assembles(headword, morphology) and len(morphology) >= 2
    if prompt_type == "letters":
        return letters_playable(str(getattr(word, "headword", "")))
    return False


def letters_playable(headword: str) -> bool:
    """字母重排能不能出题：纯英文单词、3–14 个字母、不含空格/连字符。

    太短没有重排意义，太长屏幕上摆不下；专有名词/短语不参与，避免歧义。
    """
    word = headword.strip()
    return word.isascii() and word.isalpha() and 3 <= len(word) <= 14


def validate_content_availability(words: list[Any], prompt_types: list[str]) -> None:
    """发布前校验：每种题型至少要有一个可出题词条，选择题要有足够干扰项。"""
    for prompt_type in prompt_types:
        eligible = sum(1 for w in words if word_supports_prompt_type(w, prompt_type))
        if eligible == 0:
            raise HTTPException(
                status_code=422,
                detail=_missing_content_detail(prompt_type),
            )
    if any(t in CHOICE_PROMPT_TYPES for t in prompt_types) and (
        len(words) < MIN_CHOICE_WORDS
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"选择题至少需要 {MIN_CHOICE_WORDS} 个词才能生成干扰项；"
                "请多选几个词，或去掉选择题"
            ),
        )


def _missing_content_detail(prompt_type: str) -> str:
    if prompt_type == "cloze":
        return (
            "语境填空要求词条带例句且例句包含该词本身；所选词条都不满足，"
            "请先补例句，或去掉语境填空"
        )
    if prompt_type == "roots":
        return (
            "词根拼装要求词条带词法拆解（前缀/词根/后缀），且拆解能拼回原词；"
            "所选词条都不满足，请先补词法拆解，或去掉词根拼装"
        )
    if prompt_type == "audio":
        return "纯听音任务要求每个词都有标准音"
    return f"出题方式 {prompt_type} 没有可用词条"


# ── 每题出什么题型 ─────────────────────────────────────────────────


def plan_item_prompt_types(
    words: list[Any], prompt_types: list[str]
) -> list[list[str]]:
    """逐题分配出题方式。

    - 只勾看义/听音：保持原有的双题型快照，作答端沿用「有标准音走听音、
      无音回落看义」的既有逻辑，老任务与老测试不受影响。
    - 勾了新题型：每词一个题型。分两步，保证教师勾的每种题型只要素材
      存在就真的出现（不能因为轮转顺序碰巧跳过某一种）：
      1) 先按「可选词越少越先安排」给每种题型占一个名额，并挑可用题型
         最少的词（把「什么题都能出」的词留给后面的轮转）；
      2) 剩余词按勾选顺序轮转，素材不够的词回落看义。
    """
    if set(prompt_types) <= set(LEGACY_PROMPT_TYPES):
        return [list(prompt_types) for _ in words]

    ordered = [t for t in prompt_types if t not in LEGACY_PROMPT_TYPES]
    ordered += [t for t in prompt_types if t in LEGACY_PROMPT_TYPES]

    assigned: dict[int, str] = {}
    remaining: list[tuple[int, Any]] = list(enumerate(words))

    def supports(word: Any, prompt_type: str) -> bool:
        return word_supports_prompt_type(word, prompt_type)

    def flexible(word: Any) -> int:
        return sum(1 for t in ordered if supports(word, t))

    # 1) 覆盖率：每种题型按素材稀缺程度优先占位
    sparse_first = sorted(
        ordered,
        key=lambda t: sum(1 for _, w in remaining if supports(w, t)),
    )
    for prompt_type in sparse_first:
        eligible = [item for item in remaining if supports(item[1], prompt_type)]
        if not eligible:
            continue
        index, _word = min(eligible, key=lambda item: flexible(item[1]))
        assigned[index] = prompt_type
        remaining = [item for item in remaining if item[0] != index]

    # 2) 剩余词轮转分配；都不支持时统一回落看义
    cursor = 0
    while remaining:
        placed = False
        for offset in range(len(ordered)):
            prompt_type = ordered[(cursor + offset) % len(ordered)]
            match = next(
                (item for item in remaining if supports(item[1], prompt_type)),
                None,
            )
            if match is not None:
                assigned[match[0]] = prompt_type
                remaining = [item for item in remaining if item[0] != match[0]]
                cursor = (cursor + offset + 1) % len(ordered)
                placed = True
                break
        if not placed:
            for index, _word in remaining:
                assigned[index] = "meaning"
            break

    return [[assigned[index]] for index in range(len(words))]


def pronounceable_prompt_types(prompt_types: list[str]) -> list[str]:
    """对外展示用的有序题型列表（保持教师勾选顺序）。"""
    return [t for t in prompt_types if t in VOCAB_PROMPT_TYPES]


# ── 快照载荷 ───────────────────────────────────────────────────────


def attach_prompt_payloads(
    snapshots: list[dict[str, object]], words: list[Any]
) -> None:
    """写入题型专属载荷：选项、挖空例句、打乱后的语素块。

    选项与语素块一律在这里固化，读题时不现算——否则词库改一次，
    老任务的选项就会跟着变。
    """
    from app.services.vocab_plugins import get_plugin

    for idx, (snapshot, word) in enumerate(zip(snapshots, words, strict=False)):
        prompt_type = _single_prompt_type(snapshot)
        plugin = get_plugin(prompt_type)
        # 未注册的题型不再静默补选项：宁可题面无载荷，也不给出错误选项
        if plugin is None:
            continue
        plugin.payload(idx, word, words, snapshot)


def _single_prompt_type(snapshot: dict[str, object]) -> str:
    prompt_types = snapshot.get("prompt_types")
    if isinstance(prompt_types, list) and len(prompt_types) == 1:
        return str(prompt_types[0])
    return "meaning"


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


def _build_choices(idx: int, word: Any, words: list[Any]) -> list[dict[str, object]]:
    """四选一：正确项 + 三个释义不同的干扰项，顺序按词条 ID 稳定打散。"""

    def option(w: Any) -> dict[str, object]:
        return {
            "word_id": str(w.id),
            "headword": w.headword,
            "meaning_zh": w.meaning_zh,
            "part_of_speech": w.part_of_speech,
        }

    correct_meaning = str(word.meaning_zh).strip()
    pool = [
        w
        for w in words
        if w.id != word.id and str(w.meaning_zh).strip() != correct_meaning
    ]
    pool.sort(key=lambda w: _stable_seed(word.id, w.id))
    distractors = pool[:3]
    options = [option(d) for d in distractors]
    insert_at = _stable_seed("pos", idx, word.id) % (len(options) + 1)
    options.insert(insert_at, option(word))
    return options


def _build_morph_segments(word: Any) -> list[dict[str, str]]:
    """语素块 = 真实拆解 + 两个干扰块，按词条 ID 稳定打乱。"""
    real = normalize_morphology(getattr(word, "morphology", None))
    used = {seg["text"].casefold() for seg in real}
    decoys = [
        {"text": block, "gloss": "干扰块", "kind": "root"}
        for block in MORPH_DECOY_POOL
        if block.casefold() not in used
    ][:2]
    segments = real + decoys
    segments.sort(
        key=lambda seg: _stable_seed("morph", word.id, seg["text"], seg["gloss"])
    )
    return segments


# ── 判分 ───────────────────────────────────────────────────────────


def choice_answer_matches(answer_raw: str, snapshot_item: dict[str, object]) -> bool:
    """选择题判分：提交的是所选词条 ID，与正确词条 ID 比对。

    不用「选了哪个文字」判分：同一释义可能对应多个词条，同一 headword
    也可能有多个义项，只有 ID 能唯一定位。
    """
    return answer_raw.strip().casefold() == str(snapshot_item["word_id"]).casefold()


def chosen_word_id(answer_raw: str) -> uuid.UUID | None:
    """选择题的首答存的是所选词条 ID；解析失败返回 None（老数据兼容）。"""
    try:
        return uuid.UUID(answer_raw.strip())
    except ValueError, AttributeError:
        return None


# ── 读题视图 ───────────────────────────────────────────────────────


def item_prompt_type(
    snapshot_item: dict[str, object],
    *,
    audio_allowed: bool,
) -> str:
    """该题对学生的出题方式。

    快照只有一个题型（新题型任务）时直接用；快照仍是 [meaning, audio]
    的老任务，沿用「有标准音走听音、否则看义」的既有规则。
    """
    prompt_type = _single_prompt_type(snapshot_item)
    if (
        prompt_type not in CHOICE_PROMPT_TYPES
        and prompt_type not in CONTENT_PROMPT_TYPES
    ):
        if prompt_type not in LEGACY_PROMPT_TYPES:
            return "meaning"
        if prompt_type == "audio":
            return "audio" if audio_allowed else "meaning"
        item_prompt_types = snapshot_item.get("prompt_types")
        if isinstance(item_prompt_types, list) and "audio" in item_prompt_types:
            return "audio" if audio_allowed else "meaning"
        return "meaning"
    return prompt_type


def prompt_visibility(prompt_type: str) -> tuple[bool, bool]:
    """（是否提前展示 headword, 是否提前展示中文释义）。

    英译中必须展示英文题干、藏住正确释义；中译英展示中文题干、藏住拼写；
    语境填空与词根拼装题干自带线索，释义与拼写都留到答后揭示。
    """
    if prompt_type == "en_zh":
        return True, False
    if prompt_type == "zh_en":
        return False, True
    if prompt_type in ("cloze", "roots"):
        return False, False
    return False, True


def snapshot_payload(
    snapshot_item: dict[str, object], prompt_type: str
) -> dict[str, Any]:
    """题型专属的题面载荷（未答也可下发，因为它们就是题面本身）。"""
    payload: dict[str, Any] = {}
    if prompt_type in CHOICE_PROMPT_TYPES:
        choices = snapshot_item.get("choices")
        payload["choices"] = choices if isinstance(choices, list) else []
    if prompt_type == "cloze":
        sentence = snapshot_item.get("cloze_sentence")
        payload["cloze_sentence"] = sentence if isinstance(sentence, str) else None
    if prompt_type == "roots":
        segments = snapshot_item.get("morph_segments")
        payload["morph_segments"] = segments if isinstance(segments, list) else []
    if prompt_type == "letters":
        pool = snapshot_item.get("letters_pool")
        payload["letters_pool"] = pool if isinstance(pool, list) else []
    return payload
