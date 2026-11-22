"""FSRS 复习队列域逻辑：状态写入、到期队列、每日负担、复习轮构建。

口径与不变量见 ``models/vocabulary/review.py`` 模块 docstring。要点：

- 写入只由**独立首答**（attempt_no=1）证据驱动；重试不升级/不降级状态。
- 测验（quiz）不接入：考试语义与判分口径与学习反馈分离，见接入层注释。
- 状态按 ``user_id`` 跨班汇总；队列可见性仍按当前课堂可练词库过滤，
  历史 session 与快照不被迁移或重写。
- 本模块不做长事务、不做网络调用：每次写入是短事务内的本地落库。
"""

import uuid
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    VocabularyReviewQueue,
    VocabularyReviewQueueItem,
    VocabularyReviewState,
    VocabularyReviewStats,
    VocabularySession,
    VocabularyWord,
)
from app.services import fsrs
from app.services import vocabulary as vocab_service
from app.services import vocabulary_prompt_types as prompt_types_mod

# 复习轮次类型（与旧 kind=review 错词专项明确区分，不改变其默认语义）
SESSION_KIND_REVIEW_FSRS = "review_fsrs"

_MAX_DAILY_LIMIT = 100
_MIN_DAILY_LIMIT = 1


def _daily_limit() -> int:
    """每日建议复习上限：配置值夹在 1..100 护栏内。"""
    return max(
        _MIN_DAILY_LIMIT, min(settings.VOCAB_REVIEW_DAILY_LIMIT, _MAX_DAILY_LIMIT)
    )


def _today_start_utc(now: datetime) -> datetime:
    """练习日切分（PRACTICE_TZ）：今日 00:00 对应的 UTC 时刻。"""
    tz = ZoneInfo(settings.PRACTICE_TZ)
    local_now = now.astimezone(tz)
    start_local = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    return start_local.astimezone(UTC)


def _card_from_row(row: VocabularyReviewState) -> fsrs.FSRSCard:
    return fsrs.FSRSCard(
        stability=row.stability,
        difficulty=row.difficulty,
        reps=row.reps,
        lapses=row.lapses,
        state=row.state,
        due_at=row.due_at,
        last_review_at=row.last_review_at,
        last_rating=row.last_rating,
        interval_days=row.interval_days or 1,
    )


def record_first_answer(
    session: Session,
    *,
    user_id: uuid.UUID,
    word_id: uuid.UUID,
    prompt_type: str,
    is_correct: bool,
    now: datetime | None = None,
) -> VocabularyReviewState:
    """用一条独立首答证据更新 FSRS 状态（新卡初始化 / 旧卡复习评分）。

    评分映射：答错 → again，答对 → good；不暴露 hard/easy 自评档。
    调用方必须保证只在 ``attempt_no == 1`` 且非测验轮调用——重试证据不进调度。
    """
    now = now or fsrs.utc_now()
    capability = prompt_types_mod.capability_of_prompt_type(prompt_type)
    rating = fsrs.RATING_GOOD if is_correct else fsrs.RATING_AGAIN

    existing = session.exec(
        select(VocabularyReviewState).where(
            VocabularyReviewState.user_id == user_id,  # type: ignore[arg-type]
            VocabularyReviewState.word_id == word_id,  # type: ignore[arg-type]
            VocabularyReviewState.capability == capability,  # type: ignore[arg-type]
        )
    ).first()

    if existing is None:
        card = fsrs.rate_new(rating, now)
        state = VocabularyReviewState(
            user_id=user_id,
            word_id=word_id,
            capability=capability,
            state=card.state,
            stability=card.stability,
            difficulty=card.difficulty,
            reps=card.reps,
            lapses=card.lapses,
            interval_days=card.interval_days,
            due_at=card.due_at,
            last_review_at=card.last_review_at,
            last_rating=rating,
            last_is_correct=is_correct,
        )
        session.add(state)
    else:
        # 防御：历史残留行缺复习时间戳时按新卡初始化，不把空卡当复习卡崩掉
        if existing.last_review_at is None:
            card = fsrs.rate_new(rating, now)
        else:
            card = fsrs.rate_review(_card_from_row(existing), rating, now)
        existing.state = card.state
        existing.stability = card.stability
        existing.difficulty = card.difficulty
        existing.reps = card.reps
        existing.lapses = card.lapses
        existing.interval_days = card.interval_days
        existing.due_at = card.due_at
        existing.last_review_at = card.last_review_at
        existing.last_rating = rating
        existing.last_is_correct = is_correct
        session.add(existing)
    session.commit()
    session.refresh(existing or state)  # type: ignore[arg-type]
    return existing or state  # type: ignore[return-value]


def _practiceable_states(
    session: Session, user_id: uuid.UUID, classroom_id: uuid.UUID
) -> list[VocabularyReviewState]:
    """当前可练词库内、active 词条的全部状态（归档词条状态保留但不进队列）。"""
    practiceable = vocab_service.student_practiceable_word_ids(session, classroom_id)
    if not practiceable:
        return []
    return list(
        session.exec(
            select(VocabularyReviewState).where(
                VocabularyReviewState.user_id == user_id,  # type: ignore[arg-type]
                col(VocabularyReviewState.word_id).in_(practiceable),  # type: ignore[operator]
            )
        ).all()
    )


def _load_words(
    session: Session, word_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VocabularyWord]:
    if not word_ids:
        return {}
    rows = session.exec(
        select(VocabularyWord).where(
            col(VocabularyWord.id).in_(word_ids),  # type: ignore[operator]
            VocabularyWord.status == "active",
        )
    ).all()
    return {w.id: w for w in rows}


def _queue_item(
    row: VocabularyReviewState,
    words: dict[uuid.UUID, VocabularyWord],
    now: datetime,
) -> VocabularyReviewQueueItem | None:
    word = words.get(row.word_id)
    if word is None:
        return None
    overdue = fsrs.overdue_days(row.due_at, now)
    suggested = prompt_types_mod.prompt_types_for_capability(
        row.capability, has_audio=bool(word.audio_url)
    )
    return VocabularyReviewQueueItem(
        word_id=word.id,
        headword=word.headword,
        part_of_speech=word.part_of_speech,
        meaning_zh=word.meaning_zh,
        meaning_en=word.meaning_en,
        accepted_spellings=list(word.accepted_spellings or []),
        example_en=word.example_en,
        audio_url=word.audio_url,
        morphology=prompt_types_mod.normalize_morphology(word.morphology),
        capability=row.capability,
        state=row.state,
        due_at=row.due_at,
        overdue_days=overdue,
        last_review_at=row.last_review_at,
        last_rating=row.last_rating,
        last_is_correct=row.last_is_correct,
        interval_days=row.interval_days,
        reps=row.reps,
        lapses=row.lapses,
        suggested_prompt_types=suggested,
    )


def review_queue(
    session: Session,
    *,
    user_id: uuid.UUID,
    classroom_id: uuid.UUID,
    now: datetime | None = None,
) -> VocabularyReviewQueue:
    """到期复习队列 + 每日负担摘要。

    排序：逾期天数降序 → 遗忘次数降序 → 到期时间升序 → 词条名升序。
    条目数受今日剩余额度截断；``due_today_count`` 仍是全部到期数（不截断）。
    """
    now = now or fsrs.utc_now()
    rows = _practiceable_states(session, user_id, classroom_id)
    due_rows = [r for r in rows if r.due_at <= now]
    today_start = _today_start_utc(now)
    reviewed_today = sum(
        1
        for r in rows
        if r.last_review_at is not None and r.last_review_at >= today_start
    )
    limit = _daily_limit()
    remaining = max(0, limit - reviewed_today)

    words = _load_words(session, [r.word_id for r in due_rows])
    items = [item for r in due_rows if (item := _queue_item(r, words, now)) is not None]
    items.sort(key=lambda i: (-i.overdue_days, -i.lapses, i.due_at, i.headword))
    items = items[:remaining]

    return VocabularyReviewQueue(
        classroom_code="",  # 路由层回填课堂码
        generated_at=now,
        daily_limit=limit,
        reviewed_today_count=reviewed_today,
        due_today_count=len(due_rows),
        remaining_today_count=remaining,
        items=items,
    )


def review_stats(
    session: Session,
    *,
    user_id: uuid.UUID,
    classroom_id: uuid.UUID,
    now: datetime | None = None,
) -> VocabularyReviewStats:
    """个人成长页真实复习统计（只计数，不估算记忆留存率）。"""
    now = now or fsrs.utc_now()
    rows = _practiceable_states(session, user_id, classroom_id)
    today_start = _today_start_utc(now)
    return VocabularyReviewStats(
        tracked_count=len(rows),
        due_count=sum(1 for r in rows if r.due_at <= now),
        reviewed_today_count=sum(
            1
            for r in rows
            if r.last_review_at is not None and r.last_review_at >= today_start
        ),
        learning_count=sum(1 for r in rows if r.state == "learning"),
        review_count=sum(1 for r in rows if r.state == "review"),
        recognition_count=sum(
            1 for r in rows if r.capability == prompt_types_mod.CAPABILITY_RECOGNITION
        ),
        spelling_count=sum(
            1 for r in rows if r.capability == prompt_types_mod.CAPABILITY_SPELLING
        ),
    )


def build_review_fsrs_session(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    user_id: uuid.UUID,
    word_count: int,
    now: datetime | None = None,
) -> tuple[VocabularySession, str, int]:
    """从到期队列构建一轮 FSRS 复习会话（不落库；提交与并发兜底在创建入口）。

    题单与题序创建时一次性固化；队列排序即出题顺序。复习轮独立于教师任务
    进度，不回填任务成绩。
    """
    queue = review_queue(session, user_id=user_id, classroom_id=classroom_id, now=now)
    pool = queue.items[: max(1, word_count)]
    if not pool:
        raise HTTPException(status_code=422, detail="还没有到期需要复习的词")

    words = _load_words(session, [i.word_id for i in pool])
    snapshots: list[dict[str, object]] = []
    aligned_words: list[VocabularyWord] = []
    for item in pool:
        word = words.get(item.word_id)
        if word is None:
            continue
        types = prompt_types_mod.prompt_types_for_capability(
            item.capability, has_audio=bool(word.audio_url)
        )
        snap = vocab_service.build_word_snapshot(word, types)
        snap["from_wrong"] = False
        snapshots.append(snap)
        aligned_words.append(word)

    if not snapshots:
        raise HTTPException(status_code=422, detail="还没有到期需要复习的词")
    prompt_types_mod.attach_prompt_payloads(snapshots, aligned_words)

    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=None,
        kind=SESSION_KIND_REVIEW_FSRS,
        source_book_id=None,
        snapshot_items=snapshots,
        mix_wrong=False,
        mode="practice",
        round_no=1,
    )
    return vocab_session, "复习队列", len(snapshots)
