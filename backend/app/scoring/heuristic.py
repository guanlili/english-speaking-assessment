"""跟读启发式打分（PRD §7.2 实现 A 的评分部分）。

与转写来源无关：拿到任意引擎的 transcript 后即可打分，便于测试与引擎替换。
- 完整度 = 转写词与参考文本词的多重集命中比例
- 流利度 = 语速（词/秒）偏离目标区的程度
- 总评 = 完整度 0.6 + 流利度 0.4
- 建议 = 最多两条，引用漏读的词 / 语速问题（PRD US-03）
"""

import re
from collections import Counter
from typing import TypedDict

from app.scoring.base import OpenResponseScores, ReadAloudScores

_TOKEN_RE = re.compile(r"[a-z']+")
# 原文偏移 token（保留原文大小写用于高亮，token 值小写归一）
_TOKEN_RE_RAW = re.compile(r"[a-z']+", re.IGNORECASE)
_CONSONANTS = set("bcdfghjklmnpqrstvwxyz")

# B1 学习者朗读约 120-150 词/分钟，目标 2.5 词/秒；
# 每偏离 1 词/秒扣 50 分（[1.5, 3.5] 词/秒映射到 [50, 100]）
TARGET_WPS = 2.5
WPS_PENALTY_PER_TENTH = 5.0

SILENCE_ADVICE = "没有识别到语音，请检查耳机麦克风后再试一次。"
MAX_ADVICE = 2
MISSED_WORD_COUNT = 3

MIN_WPS_SLOW = 1.5
MAX_WPS_FAST = 3.5


def tokenize(text: str) -> list[str]:
    """小写化并抽出英文单词（撇号归属单词，如 don't）。"""
    return _TOKEN_RE.findall(text.lower())


def tokenize_with_spans(text: str) -> list[tuple[str, int, int]]:
    """(小写 token, start, end)：end 为原文中的闭偏移（高亮渲染用原文切片）。"""
    return [
        (m.group(0).lower(), m.start(), m.end()) for m in _TOKEN_RE_RAW.finditer(text)
    ]


def lemma_variants(token: str) -> list[str]:
    """轻量词元归一：只处理规则屈折（复数/进行时/过去式）。

    只从参考词（题目原文，拼写规范）单向生成变体；不做 -er/-est 截词
    （mother/flower/teacher 等 -er 名词会与比较级混淆，宁可标 error）。
    """
    variants = [token]
    if token.endswith("ies") and len(token) > 4:
        variants.append(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        variants.append(token[:-2])
    if token.endswith("s") and len(token) > 2:
        variants.append(token[:-1])
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        variants.append(stem)
        variants.append(stem + "e")  # making → make
        if (
            len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] in _CONSONANTS
        ):  # running → run
            variants.append(stem[:-1])
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        variants.append(stem)
        variants.append(token[:-1])  # hoped → hope
        if (
            len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] in _CONSONANTS
        ):  # stopped → stop
            variants.append(stem[:-1])
    return list(dict.fromkeys(variants))


class AlignedWord(TypedDict):
    start: int
    end: int
    text: str  # 参考原文切片（保留原大小写）
    status: str  # correct | missing | error
    heard: str | None  # error 时：转写中听到的形式


class WordAlignment(TypedDict):
    words: list[AlignedWord]
    extras: list[dict[str, str]]  # 转写中多读的词


def _variant_match(reference_token: str, spoken_token: str) -> bool:
    """读对判定：一方的完整拼写精确等于另一方的规则屈折变体。

    只做「词 → 规则变体」的精确包含（dog 在 dogs 的变体里 = 读对；
    moth 不在 mother 的变体里 = 读错），不做截词候选的交集——
    交集会把 mother/moth、flower/flow、hoping/hopping 这类拼写不同的词
    误判成等价。
    """
    if reference_token == spoken_token:
        return True
    return spoken_token in set(
        lemma_variants(reference_token)
    ) or reference_token in set(lemma_variants(spoken_token))


def align_words(reference: str, transcript: str) -> WordAlignment:
    """把转写词对齐到参考词（编辑距离 DP），给每个参考词打状态。

    - correct：有转写词对齐且词形变体命中（dogs → dog 算读对）
    - error：有转写词对齐但形式不符（heard 记录听到的形式）
    - missing：参考词没有对齐到任何转写词（漏读）
    - extras：转写中多出的词（多读）

    结果只用于展示与个人漏词聚合，不参与评分口径（评分仍走多重集命中）。
    """
    ref_tokens = tokenize_with_spans(reference)
    spoken_tokens = tokenize_with_spans(transcript)
    if not ref_tokens:
        return {"words": [], "extras": []}
    if not spoken_tokens:
        return {
            "words": [
                {
                    "start": start,
                    "end": end,
                    "text": reference[start:end],
                    "status": "missing",
                    "heard": None,
                }
                for _token, start, end in ref_tokens
            ],
            "extras": [],
        }

    rows, cols = len(ref_tokens), len(spoken_tokens)
    # cost[i][j]：前 i 个参考词对齐前 j 个转写词的最小代价
    cost = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows + 1):
        cost[i][0] = i
    for j in range(cols + 1):
        cost[0][j] = j
    for i in range(1, rows + 1):
        ref_token = ref_tokens[i - 1][0]
        for j in range(1, cols + 1):
            match_cost = 0 if _variant_match(ref_token, spoken_tokens[j - 1][0]) else 2
            cost[i][j] = min(
                cost[i - 1][j - 1] + match_cost,
                cost[i - 1][j] + 1,
                cost[i][j - 1] + 1,
            )

    # 回溯：matched[i] = None(missing) | ("correct", spoken_idx) | ("error", spoken_idx)
    matched: list[tuple[str, int] | None] = [None] * rows
    used_spoken: list[bool] = [False] * cols
    i, j = rows, cols
    while i > 0 and j > 0:
        ref_token = ref_tokens[i - 1][0]
        same = _variant_match(ref_token, spoken_tokens[j - 1][0])
        match_cost = 0 if same else 2
        if cost[i][j] == cost[i - 1][j - 1] + match_cost:
            matched[i - 1] = ("correct" if same else "error", j - 1)
            used_spoken[j - 1] = True
            i -= 1
            j -= 1
        elif cost[i][j] == cost[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1

    extras = [{"text": spoken_tokens[k][0]} for k in range(cols) if not used_spoken[k]]
    words: list[AlignedWord] = []
    for idx, (_token, start, end) in enumerate(ref_tokens):
        entry: AlignedWord = {
            "start": start,
            "end": end,
            "text": reference[start:end],
            "status": "missing",
            "heard": None,
        }
        entry_match = matched[idx]
        if entry_match is not None:
            kind, spoken_idx = entry_match
            entry["status"] = kind
            if kind == "error":
                entry["heard"] = spoken_tokens[spoken_idx][0]
        words.append(entry)
    return {"words": words, "extras": extras}


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def completeness_score(
    transcript_tokens: list[str], reference_tokens: list[str]
) -> int:
    """多重集命中比例：多读不加分，漏读按比例扣分。"""
    if not reference_tokens:
        return 0
    remaining = Counter(reference_tokens)
    hits = 0
    for token in transcript_tokens:
        if remaining.get(token, 0) > 0:
            hits += 1
            remaining[token] -= 1
    return _clamp_score(100 * hits / len(reference_tokens))


def fluency_score(word_count: int, duration_s: float) -> int:
    """语速越接近目标区越高；无语音（0 词）为 0 分。"""
    if word_count <= 0 or duration_s <= 0:
        return 0
    wps = word_count / duration_s
    deviation_tenths = abs(wps - TARGET_WPS) * 10
    return _clamp_score(100 - deviation_tenths * WPS_PENALTY_PER_TENTH)


def build_advice(
    transcript_tokens: list[str],
    reference_tokens: list[str],
    duration_s: float,
    suggested_seconds: int,
) -> list[str]:
    advice: list[str] = []
    if not transcript_tokens:
        return [SILENCE_ADVICE]

    spoken_set = set(transcript_tokens)
    missed = [w for w in reference_tokens if w not in spoken_set]
    # 去重保持顺序，取前几个
    missed_unique = list(dict.fromkeys(missed))[:MISSED_WORD_COUNT]
    if missed_unique and len(missed) > len(reference_tokens) * 0.2:
        advice.append(f"试着把这些词读出来：{', '.join(missed_unique)}。")

    wps = len(transcript_tokens) / max(duration_s, 0.1)
    if wps > MAX_WPS_FAST:
        advice.append("语速偏快，放慢一点会更清楚。")
    elif wps < MIN_WPS_SLOW or duration_s < suggested_seconds * 0.5:
        advice.append("录音偏短或语速偏慢，试着更连贯地读完整段。")

    return advice[:MAX_ADVICE]


def score_read_aloud(
    transcript: str,
    reference_text: str,
    duration_s: float,
    suggested_seconds: int = 45,
) -> ReadAloudScores:
    transcript_tokens = tokenize(transcript)
    reference_tokens = tokenize(reference_text)

    completeness = completeness_score(transcript_tokens, reference_tokens)
    fluency = fluency_score(len(transcript_tokens), duration_s)
    overall = _clamp_score(0.6 * completeness + 0.4 * fluency)

    return ReadAloudScores(
        transcript=transcript.strip(),
        completeness=completeness,
        fluency=fluency,
        accuracy=completeness,  # 启发式阶段与完整度同源；接讯飞/Azure 后独立
        overall=overall,
        advice=build_advice(
            transcript_tokens, reference_tokens, duration_s, suggested_seconds
        ),
    )


# 开放问答（无参考文本）：内容量 + 语速的启发式。
# 即兴说话比朗读慢，目标语速降到 2.0 词/秒；25 词 ≈ 内容满分。
OPEN_TARGET_WPS = 2.0
OPEN_FULL_MARK_WORDS = 25
OPEN_FAST_WPS = 3.5
OPEN_FEW_WORDS = 10


def score_open_response(transcript: str, duration_s: float) -> OpenResponseScores:
    tokens = tokenize(transcript)
    if not tokens:
        return OpenResponseScores(
            transcript="",
            fluency=0,
            overall=0,
            advice=[SILENCE_ADVICE],
        )

    wps = len(tokens) / max(duration_s, 0.1)
    fluency = _clamp_score(
        100 - abs(wps - OPEN_TARGET_WPS) * 10 * WPS_PENALTY_PER_TENTH
    )
    content = _clamp_score(100 * len(tokens) / OPEN_FULL_MARK_WORDS)
    overall = _clamp_score(0.6 * content + 0.4 * fluency)

    if len(tokens) < OPEN_FEW_WORDS:
        advice = "试着再多说两句，比如加一个例子（for example…）。"
    elif wps > OPEN_FAST_WPS:
        advice = "语速偏快，放慢一点、说完整句子会更清楚。"
    else:
        advice = "回答得不错，试着用 because 或 for example 再补一句理由。"

    return OpenResponseScores(
        transcript=transcript.strip(),
        fluency=fluency,
        overall=overall,
        advice=[advice],
    )
