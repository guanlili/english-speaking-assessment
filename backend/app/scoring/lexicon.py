"""词表命中分析（PRD §7.2 LexiconScorer，3 周启用）。

纯本地：不调用任何外部服务。只统计开放问答转写，
跟读参考文本里的词不算学生的词汇（PRD US-07）。
"""

import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[a-z']+")

# PRD US-07 标签规则：最高稳定档（至少命中 5 个该档词）即该档，否则降一档
STABLE_BAND_HITS = 5

BAND_ORDER = ["A2", "B1", "B2"]


@dataclass
class VocabAnalysis:
    hits_by_band: dict[str, list[str]] = field(default_factory=dict)
    coverage_ratio: float = 0.0  # 命中词元数 / 转写实词（去重）数
    cefr_label: str | None = None


def _lemma_variants(token: str) -> list[str]:
    """轻量词元归一：处理规则屈折（复数/进行时/过去式），不规则形式由词表直接收录。"""
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
        if len(stem) > 2 and stem[-1] == stem[-2]:  # running → run
            variants.append(stem[:-1])
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        variants.append(stem)
        variants.append(token[:-1])  # hoped → hope
        if len(stem) > 2 and stem[-1] == stem[-2]:  # stopped → stop
            variants.append(stem[:-1])
    if token.endswith("er") and len(token) > 4:
        variants.append(token[:-2])
        variants.append(token[:-1])
    if token.endswith("est") and len(token) > 5:
        variants.append(token[:-3])
        variants.append(token[:-2])
    return list(dict.fromkeys(variants))


def _match(token: str, lemmas_by_band: dict[str, set[str]]) -> str | None:
    """一个词命中多档时按最高档计（PRD：展示学生的最高稳定档）。"""
    for band in reversed(BAND_ORDER):
        for variant in _lemma_variants(token):
            if variant in lemmas_by_band.get(band, set()):
                return band
    return None


def analyze_transcript(
    transcript: str, lemmas_by_band: dict[str, set[str]]
) -> VocabAnalysis:
    """统计转写命中的分级词。一个词只按其最高档计一次。

    覆盖比例 = 命中词数（去重）/ 转写词数（去重）——PRD US-07 的粗口径。
    """
    tokens = _TOKEN_RE.findall(transcript.lower())
    unique_tokens = set(tokens)
    if not unique_tokens or not any(lemmas_by_band.values()):
        return VocabAnalysis(cefr_label=None)

    hits_by_band: dict[str, list[str]] = {band: [] for band in BAND_ORDER}
    for token in sorted(unique_tokens):
        band = _match(token, lemmas_by_band)
        if band is not None:
            # 记录的是原词形（界面展示用），按最高命中档归类
            hits_by_band[band].append(token)

    total_hits = sum(len(words) for words in hits_by_band.values())
    coverage = total_hits / len(unique_tokens)

    # 标签：最高稳定档（≥5 命中）；否则最高有命中档降一档；无命中 → A2
    label = "A2"
    highest_hit: str | None = None
    for band in reversed(BAND_ORDER):
        if len(hits_by_band[band]) >= STABLE_BAND_HITS:
            label = band
            break
        if highest_hit is None and hits_by_band[band]:
            highest_hit = band
    if label == "A2" and highest_hit is not None:
        label = BAND_ORDER[max(0, BAND_ORDER.index(highest_hit) - 1)]

    return VocabAnalysis(
        hits_by_band=hits_by_band,
        coverage_ratio=round(coverage, 2),
        cefr_label=label,
    )
