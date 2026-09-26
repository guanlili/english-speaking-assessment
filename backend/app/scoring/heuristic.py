"""跟读启发式打分（PRD §7.2 实现 A 的评分部分）。

与转写来源无关：拿到任意引擎的 transcript 后即可打分，便于测试与引擎替换。
- 完整度 = 转写词与参考文本词的多重集命中比例
- 流利度 = 语速（词/秒）偏离目标区的程度
- 总评 = 完整度 0.6 + 流利度 0.4
- 建议 = 最多两条，引用漏读的词 / 语速问题（PRD US-03）
"""

import re
from collections import Counter

from app.scoring.base import OpenResponseScores, ReadAloudScores

_TOKEN_RE = re.compile(r"[a-z']+")

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
