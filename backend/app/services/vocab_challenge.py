"""每日挑战：每天按「日期 + 班级」seed 组合 3 款不同维度的练习（#618 第一段）。

口径：

- **可复现**：同一班级同一天，任何人拿到的是同一套配置（seed = 班级 + 日期）；
  题库内容按词条 ID 稳定排序取词，词库不改就完全一致。
- **3 款不同维度**：维度 = 拼写 / 认读 / 语境 / 词法；每维最多出 1 款，
  所以「3 款」天然互不重复，不会出现三套都是选择题。
- **独立口径**：挑战轮 `kind="daily_challenge"`，不进教师任务统计、不改任务
  首答成绩、不参与错词本/坐标以外的任何排行；作答仍按原判分链路留痕。
- **素材不足就降级**：某维度没有够题的词时直接跳过并给出原因，不凑空题、
  不硬塞无素材玩法；最少出 1 款，0 款时明确返回「今日素材不足」。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlmodel import Session, col, select

from app.models import (
    VocabularyBook,
    VocabularyBookItem,
    VocabularySession,
    VocabularyWord,
)
from app.services import vocabulary as vocab_service
from app.services import vocabulary_prompt_types as prompt_types_mod

CHALLENGE_KIND = "daily_challenge"
CHALLENGE_BLOCKS = 3
CHALLENGE_WORDS_PER_BLOCK = 5
# 一个维度至少要有这么多词能出题，才会被选进当日挑战
CHALLENGE_MIN_WORDS_PER_BLOCK = 3

# 维度 → 可用玩法（同维度内只取 1 款，保证「3 款不同维度」）
CHALLENGE_DIMENSIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("spelling", "拼写", ("meaning", "audio")),
    ("recognition", "认读", ("en_zh", "zh_en")),
    ("context", "语境", ("cloze",)),
    ("morphology", "词法", ("roots",)),
)

DIMENSION_LABELS: dict[str, tuple[str, str]] = {
    "spelling": ("拼写", "Spelling"),
    "recognition": ("认读", "Recognition"),
    "context": ("语境", "Context"),
    "morphology": ("词法", "Morphology"),
}


@dataclass(frozen=True)
class ChallengeBlock:
    """今日挑战里的一块：一个玩法 + 本次要考的单词。"""

    dimension: str
    key: str
    word_ids: tuple[uuid.UUID, ...]

    @property
    def item_count(self) -> int:
        return len(self.word_ids)


@dataclass
class ChallengePack:
    """一天一套的挑战包（可复现；不含学生作答状态）。"""

    day: date
    blocks: list[ChallengeBlock] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        return len(self.blocks) < CHALLENGE_BLOCKS

    @property
    def total_items(self) -> int:
        return sum(b.item_count for b in self.blocks)


def challenge_day(now: datetime | None = None) -> date:
    """挑战日期（按 UTC+8 的本地日界，与前端「今天」一致）。"""
    from app.models.base import get_datetime_utc

    moment = now or get_datetime_utc()
    return moment.date()


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


def _student_words(session: Session, classroom_id: uuid.UUID) -> list[VocabularyWord]:
    """本人当前可练词表（active 公共库 + 本班库内 approved active 词条）。

    同一词可能挂在多个词库（公共库 + 班级库），按词条 ID 去重。
    """
    stmt = (
        select(VocabularyWord)
        .join(
            VocabularyBookItem,
            col(VocabularyBookItem.word_id) == VocabularyWord.id,
        )
        .join(
            VocabularyBook,
            col(VocabularyBook.id) == VocabularyBookItem.book_id,
        )
        .where(
            VocabularyBook.status == "active",
            VocabularyWord.status == "active",
            VocabularyWord.review_status == "approved",
            (VocabularyBook.scope == "public")  # type: ignore[operator]
            | (VocabularyBook.classroom_id == classroom_id),  # type: ignore[operator,arg-type]
        )
    )
    seen: set[uuid.UUID] = set()
    words: list[VocabularyWord] = []
    for word in session.exec(stmt).all():
        if word.id in seen:
            continue
        seen.add(word.id)
        words.append(word)
    return words


def compose_pack(session: Session, classroom_id: uuid.UUID, day: date) -> ChallengePack:
    """按「班级 + 日期」seed 组一套挑战包（同一输入永远同一输出）。"""
    words = _student_words(session, classroom_id)
    pack = ChallengePack(day=day)
    if not words:
        pack.skipped["all"] = "当前没有可练词表，先让老师建词库/派词"
        return pack

    usable = sorted(words, key=lambda w: _stable_seed(day, classroom_id, w.id))
    used: set[uuid.UUID] = set()

    # 维度顺序由 seed 决定：同一天同班固定，不同班/不同天轮换
    dimensions = list(CHALLENGE_DIMENSIONS)
    dimensions.sort(key=lambda item: _stable_seed(day, classroom_id, item[0]))

    for dimension, label_zh, keys in dimensions:
        if len(pack.blocks) >= CHALLENGE_BLOCKS:
            break
        best: tuple[int, str, list[VocabularyWord]] | None = None
        for key in keys:
            eligible = [
                w
                for w in usable
                if w.id not in used
                and prompt_types_mod.word_supports_prompt_type(w, key)
            ]
            if len(eligible) < CHALLENGE_MIN_WORDS_PER_BLOCK:
                continue
            candidate = (len(eligible), key, eligible[:CHALLENGE_WORDS_PER_BLOCK])
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            pack.skipped[dimension] = f"{label_zh}维度素材不够"
            continue
        _count, key, picked = best
        used.update(w.id for w in picked)
        pack.blocks.append(
            ChallengeBlock(
                dimension=dimension, key=key, word_ids=tuple(w.id for w in picked)
            )
        )

    if not pack.blocks:
        pack.skipped.setdefault("all", "今天所有维度的素材都不足，暂不出挑战")
    return pack


def _snapshot_items(session: Session, pack: ChallengePack) -> list[dict[str, object]]:
    """把挑战包固化成题单（与任务/自主轮同一套快照结构）。"""
    word_ids = [wid for block in pack.blocks for wid in block.word_ids]
    words = list(
        session.exec(
            select(VocabularyWord).where(col(VocabularyWord.id).in_(word_ids))  # type: ignore[operator]
        ).all()
    )
    by_id = {w.id: w for w in words}
    ordered: list[tuple[VocabularyWord, list[str]]] = []
    for block in pack.blocks:
        for wid in block.word_ids:
            word = by_id.get(wid)
            if word is not None:
                ordered.append((word, [block.key]))
    if not ordered:
        return []
    snapshots = [
        vocab_service.build_word_snapshot(word, types) for word, types in ordered
    ]
    prompt_types_mod.attach_prompt_payloads(snapshots, [w for w, _ in ordered])
    return snapshots


def start_challenge(
    session: Session, *, classroom_id: uuid.UUID, student_id: uuid.UUID, day: date
) -> VocabularySession | None:
    """开今天的挑战轮（同一学生同一天续做上一次未完成的轮，不重复开）。"""
    existing = session.exec(
        select(VocabularySession)
        .where(
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            VocabularySession.kind == CHALLENGE_KIND,  # type: ignore[arg-type]
            VocabularySession.status == "in_progress",  # type: ignore[arg-type]
        )
        .order_by(col(VocabularySession.started_at).desc())
    ).first()
    if existing is not None and _session_day(existing) == day:
        return existing

    pack = compose_pack(session, classroom_id, day)
    items = _snapshot_items(session, pack)
    if not items:
        return None
    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=None,
        kind=CHALLENGE_KIND,
        source_book_id=None,
        snapshot_items=items,
        mix_wrong=False,
        mode="practice",
        round_no=1,
    )
    session.add(vocab_session)
    session.commit()
    session.refresh(vocab_session)
    return vocab_session


def _session_day(vocab_session: VocabularySession) -> date | None:
    started = vocab_session.started_at
    return started.date() if started is not None else None


def todays_session(
    session: Session, student_id: uuid.UUID, day: date
) -> VocabularySession | None:
    """今天已开过的挑战轮（含已完成），用于展示完成状态。"""
    rows = session.exec(
        select(VocabularySession)
        .where(
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            VocabularySession.kind == CHALLENGE_KIND,  # type: ignore[arg-type]
        )
        .order_by(col(VocabularySession.started_at).desc())
    ).all()
    for row in rows:
        if _session_day(row) == day:
            return row
    return None


def class_participation(
    session: Session, classroom_id: uuid.UUID, day: date
) -> tuple[int, int]:
    """(今天已开挑战的人数, 今天已完成的人数) —— 教师端只读参与情况。"""
    rows = session.exec(
        select(
            VocabularySession.student_id,
            VocabularySession.status,
            VocabularySession.started_at,
        ).where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularySession.kind == CHALLENGE_KIND,  # type: ignore[arg-type]
        )
    ).all()
    started: set[uuid.UUID] = set()
    completed: set[uuid.UUID] = set()
    for student_id, status, started_at in rows:
        if started_at is None or started_at.date() != day:
            continue
        started.add(student_id)
        if status == "submitted":
            completed.add(student_id)
    return len(started), len(completed)


def challenge_payload(
    pack: ChallengePack,
    *,
    classroom_code: str,
    vocab_session: VocabularySession | None,
) -> dict[str, object]:
    """把内部结构转成接口载荷（教师/学生共用，字段稳定）。"""
    return {
        "classroom_code": classroom_code,
        "date": pack.day.isoformat(),
        "degraded": pack.degraded,
        "reason": "；".join(sorted(pack.skipped.values())) or None,
        "blocks": [
            {
                "dimension": block.dimension,
                "key": block.key,
                "item_count": block.item_count,
            }
            for block in pack.blocks
        ],
        "total_items": pack.total_items,
        "completed": bool(vocab_session and vocab_session.status == "submitted"),
        "session_id": str(vocab_session.id) if vocab_session else None,
    }
