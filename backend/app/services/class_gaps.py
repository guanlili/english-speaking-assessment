"""当前发布的全班薄弱点：用已有转写对齐参考文本，不另接发音引擎。"""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.models import AttemptItemType
from app.scoring.heuristic import tokenize

# 功能词不进「全班漏词」：课上讲评要看到内容词，而不是 the / a。
_FUNCTION_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "my",
        "your",
        "his",
        "her",
        "our",
        "their",
        "this",
        "that",
        "with",
        "from",
        "as",
        "but",
        "not",
        "so",
        "if",
    }
)

LOW_OVERALL = 70
WEAK_AVG = 80
MAX_WORDS = 8
MAX_ITEMS = 3
LABEL_CHARS = 48


def missed_content_words(reference: str, transcript: str) -> list[str]:
    """参考文本里出现、转写里没有的内容词，保持原文顺序并去重。"""
    spoken = set(tokenize(transcript))
    missed: list[str] = []
    seen: set[str] = set()
    for word in tokenize(reference):
        if word in _FUNCTION_WORDS or word in spoken or word in seen:
            continue
        seen.add(word)
        missed.append(word)
    return missed


def aggregate_word_gaps(
    rows: list[tuple[uuid.UUID, str, str]],
) -> list[tuple[str, int]]:
    """(student_id, reference, transcript) → 至少两名学生漏读的词。

    只有一名学生交了朗读/复述时，阈值降为 1，一对一课堂也能看到漏词。
    """
    missed_by: dict[str, set[uuid.UUID]] = defaultdict(set)
    students: set[uuid.UUID] = set()
    for student_id, reference, transcript in rows:
        if not reference.strip():
            continue
        students.add(student_id)
        for word in missed_content_words(reference, transcript):
            missed_by[word].add(student_id)
    threshold = 1 if len(students) < 2 else 2
    ranked = [
        (word, len(ids)) for word, ids in missed_by.items() if len(ids) >= threshold
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[:MAX_WORDS]


def aggregate_low_items(
    rows: list[tuple[uuid.UUID, uuid.UUID, str, str, int | None]],
) -> list[dict[str, object]]:
    """(student_id, item_id, item_type, label, overall) → 均分偏低或多人低于 70 的题。"""
    grouped: dict[uuid.UUID, dict[str, object]] = {}
    for _student_id, item_id, item_type, label, overall in rows:
        if item_type == AttemptItemType.INSTRUCTION or overall is None:
            continue
        bucket = grouped.setdefault(
            item_id,
            {
                "item_id": item_id,
                "item_type": item_type,
                "label": label,
                "scores": [],
            },
        )
        scores = bucket["scores"]
        assert isinstance(scores, list)
        scores.append(overall)
    notable: list[dict[str, object]] = []
    for bucket in grouped.values():
        scores = bucket["scores"]
        assert isinstance(scores, list)
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        low_count = sum(1 for score in scores if score < LOW_OVERALL)
        need = 1 if len(scores) < 2 else 2
        if avg >= WEAK_AVG and low_count < need:
            continue
        notable.append(
            {
                "item_id": bucket["item_id"],
                "item_type": bucket["item_type"],
                "label": bucket["label"],
                "scored_count": len(scores),
                "avg_overall": round(avg, 1),
                "low_count": low_count,
            }
        )
    notable.sort(
        key=lambda item: (
            float(item["avg_overall"]),  # type: ignore[arg-type]
            -int(item["low_count"]),  # type: ignore[arg-type]
        )
    )
    return notable[:MAX_ITEMS]


def snapshot_label(snapshot: dict[str, object] | None, item_type: str) -> str:
    if snapshot is None:
        return item_type
    raw = snapshot.get("title") or snapshot.get("text") or ""
    text = str(raw).strip().replace("\n", " ")
    if len(text) > LABEL_CHARS:
        return f"{text[: LABEL_CHARS - 1]}…"
    return text or item_type
