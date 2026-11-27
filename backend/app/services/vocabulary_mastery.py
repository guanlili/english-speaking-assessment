"""班级词汇掌握度聚合（教师视角）。

口径不变量（与产品口径对齐，前后端文案一致遵守）：

- **掌握度不是考试分数、不是能力等级**：它只汇总窗口内本班教师任务轮
  （``kind=task``）的首答正确率分段、FSRS 复习状态分布与到期未复习条目数，
  用于安排复习，不对外宣称能力认证。
- **首答是唯一作答口径**：只统计 ``attempt_no=1``；重试轮次不冲高正确率。
  自主练习（``self``）、错词复习（``review``）、FSRS 队列（``review_fsrs``）
  以及后续接入的分班测（placement）一律不混入。
- **零作答不画成 0%**：窗口内没有首答的词标 ``no_data``，正确率为 ``None``。
- **``wrong_count`` 不进掌握度**：历史错误次数只增不减，与本模块的分段、
  状态分布互不改写。
- **到期口径是状态条目数**：``due_count`` 统计 ``user × word × capability``
  条目，不是去重后的词数；FSRS 状态按在册学生账号汇总（跨班连续性见
  ``models/vocabulary/review.py``）。
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    Student,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyMasteryReport,
    VocabularyMasteryWordRow,
    VocabularyReviewState,
    VocabularySession,
    get_datetime_utc,
)
from app.models.vocabulary.reports import MASTERY_WINDOW_DAYS
from app.models.vocabulary.review import (
    REVIEW_STATE_LEARNING,
    REVIEW_STATE_NEW,
    REVIEW_STATE_REVIEW,
)

# 教师任务轮标识（与 vocabulary_session.kind 默认值一致）
SESSION_KIND_TASK = "task"

# 分段阈值：<60% 偏弱；60–85%（含 60 与 85）中等；>85% 较稳
ACCURACY_LOW_MAX = 60
ACCURACY_MID_MAX = 85

_BAND_ORDER = {"low": 0, "mid": 1, "high": 2, "no_data": 3}


def first_try_accuracy(correct: int, answered: int) -> int | None:
    """首答正确率（0..100 取整）；零作答返回 None（界面显示 –，不折算 0%）。"""
    if answered <= 0:
        return None
    return round(correct / answered * 100)


def mastery_band(correct: int, answered: int) -> tuple[int | None, str]:
    """按首答正确/已答数算正确率与分段。

    分段在**展示用取整正确率**上判定，避免「显示 85% 却落高档」的错位：
    ``<60`` → low；``60..85``（含边界）→ mid；``>85`` → high；无首答 → no_data。
    """
    pct = first_try_accuracy(correct, answered)
    if pct is None:
        return None, "no_data"
    if pct < ACCURACY_LOW_MAX:
        band = "low"
    elif pct <= ACCURACY_MID_MAX:
        band = "mid"
    else:
        band = "high"
    return pct, band


def _snapshot_universe(
    snapshot_items: list[dict[str, object]] | None,
) -> dict[uuid.UUID, dict[str, str]]:
    """任务快照词条去重汇总：word_id → {headword, meaning_zh}。"""
    universe: dict[uuid.UUID, dict[str, str]] = {}
    for item in snapshot_items or []:
        raw_id = item.get("word_id")
        if raw_id is None:
            continue
        try:
            word_id = uuid.UUID(str(raw_id))
        except ValueError:
            continue
        universe.setdefault(
            word_id,
            {
                "headword": str(item.get("headword") or ""),
                "meaning_zh": str(item.get("meaning_zh") or ""),
            },
        )
    return universe


def _first_answer_stats(
    session: Session,
    classroom_id: uuid.UUID,
    assignment: VocabularyAssignment | None,
    cutoff: datetime,
) -> dict[uuid.UUID, dict[str, Any]]:
    """窗口内本班教师任务轮首答，按词条聚合已答/首答正确数。

    只取 ``kind=task`` 会话的 ``attempt_no=1`` 答案；assignment 给定后再按
    任务过滤。作答时间落在窗口内（``answered_at >= cutoff``）。
    """
    stmt = (
        select(VocabularyAnswer)
        .join(
            VocabularySession,
            VocabularySession.id == VocabularyAnswer.session_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularySession.kind == SESSION_KIND_TASK,
            VocabularySession.round_no == 1,
            VocabularyAnswer.attempt_no == 1,
            col(VocabularyAnswer.answered_at) >= cutoff,  # type: ignore[operator]
        )
    )
    if assignment is not None:
        stmt = stmt.where(VocabularySession.assignment_id == assignment.id)  # type: ignore[arg-type]

    stats: dict[uuid.UUID, dict[str, Any]] = {}
    for answer in session.exec(stmt).all():
        bucket = stats.setdefault(
            answer.word_id,
            {
                "answered": 0,
                "correct": 0,
                "headword": answer.headword,
                "meaning_zh": answer.meaning_zh,
            },
        )
        bucket["answered"] += 1
        if answer.is_correct:
            bucket["correct"] += 1
    return stats


def _fsrs_by_word(
    session: Session,
    classroom_id: uuid.UUID,
    universe: list[uuid.UUID],
    now: datetime,
) -> dict[uuid.UUID, dict[str, int]]:
    """在册学生在本视图词条上的 FSRS 状态条目分布（按词条分组）。

    返回 ``word_id → {new, learning, review, due}``；``due`` 为已到期（含逾期）
    条目数。只统计在册学生账号，归档/跨班遗留状态不进本班口径。
    """
    member_user_ids = [
        student.user_id
        for student in session.exec(
            select(Student).where(Student.classroom_id == classroom_id)  # type: ignore[arg-type]
        ).all()
        if student.user_id is not None
    ]
    empty: dict[uuid.UUID, dict[str, int]] = {}
    if not member_user_ids or not universe:
        return empty

    rows = session.exec(
        select(VocabularyReviewState).where(
            col(VocabularyReviewState.user_id).in_(member_user_ids),  # type: ignore[operator]
            col(VocabularyReviewState.word_id).in_(universe),  # type: ignore[operator]
        )
    ).all()

    grouped: dict[uuid.UUID, dict[str, int]] = {}
    for state in rows:
        bucket = grouped.setdefault(
            state.word_id,
            {
                REVIEW_STATE_NEW: 0,
                REVIEW_STATE_LEARNING: 0,
                REVIEW_STATE_REVIEW: 0,
                "due": 0,
            },
        )
        if state.state in (
            REVIEW_STATE_NEW,
            REVIEW_STATE_LEARNING,
            REVIEW_STATE_REVIEW,
        ):
            bucket[state.state] += 1
        if state.due_at is not None and state.due_at <= now:
            bucket["due"] += 1
    return grouped


def class_vocabulary_mastery(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    classroom_code: str,
    assignment: VocabularyAssignment | None,
    window_days: int,
    now: datetime | None = None,
) -> VocabularyMasteryReport:
    """聚合班级掌握度载荷。

    ``assignment`` 为空 = ``all_tasks`` 口径（本班全部教师任务）；给定 =
    ``assignment`` 口径（单任务快照词条全集，未答词标 no_data）。
    """
    now = now or get_datetime_utc()
    cutoff = now - timedelta(days=window_days)

    stats = _first_answer_stats(session, classroom_id, assignment, cutoff)

    # 词条全集：单任务取其快照；全部任务取本班所有任务快照的并集
    universe: dict[uuid.UUID, dict[str, str]] = {}
    if assignment is not None:
        universe = _snapshot_universe(assignment.snapshot_items)
    else:
        assignments = session.exec(
            select(VocabularyAssignment).where(
                VocabularyAssignment.classroom_id == classroom_id  # type: ignore[arg-type]
            )
        ).all()
        for item_assignment in assignments:
            universe.update(_snapshot_universe(item_assignment.snapshot_items))
    # 防御：窗口答案里出现了快照之外的词（历史快照缺失等），补齐进视图
    for word_id, bucket in stats.items():
        universe.setdefault(
            word_id,
            {
                "headword": str(bucket["headword"]),
                "meaning_zh": str(bucket["meaning_zh"]),
            },
        )

    fsrs = _fsrs_by_word(session, classroom_id, list(universe.keys()), now)

    rows: list[VocabularyMasteryWordRow] = []
    for word_id, meta in universe.items():
        bucket = stats.get(word_id)
        answered = int(bucket["answered"]) if bucket else 0
        correct = int(bucket["correct"]) if bucket else 0
        accuracy_rate, band = mastery_band(correct, answered)
        states = fsrs.get(word_id, {})
        rows.append(
            VocabularyMasteryWordRow(
                word_id=word_id,
                headword=meta["headword"],
                meaning_zh=meta["meaning_zh"],
                answered_count=answered,
                correct_first_count=correct,
                accuracy_rate=accuracy_rate,
                band=band,
                fsrs_new=states.get(REVIEW_STATE_NEW, 0),
                fsrs_learning=states.get(REVIEW_STATE_LEARNING, 0),
                fsrs_review=states.get(REVIEW_STATE_REVIEW, 0),
                due_count=states.get("due", 0),
            )
        )

    # 偏弱的词排前面：分段 low → mid → high → no_data；同段按正确率升序
    rows.sort(
        key=lambda r: (
            _BAND_ORDER.get(r.band, len(_BAND_ORDER)),
            r.accuracy_rate if r.accuracy_rate is not None else 101,
            r.headword.lower(),
        )
    )

    answered_total = sum(row.answered_count for row in rows)
    correct_total = sum(row.correct_first_count for row in rows)
    return VocabularyMasteryReport(
        classroom_code=classroom_code,
        generated_at=now,
        window_days=window_days,
        scope="assignment" if assignment is not None else "all_tasks",
        assignment_id=assignment.id if assignment is not None else None,
        answered_count=answered_total,
        correct_first_count=correct_total,
        accuracy_rate=first_try_accuracy(correct_total, answered_total),
        low_count=sum(1 for row in rows if row.band == "low"),
        mid_count=sum(1 for row in rows if row.band == "mid"),
        high_count=sum(1 for row in rows if row.band == "high"),
        no_data_count=sum(1 for row in rows if row.band == "no_data"),
        fsrs_new=sum(row.fsrs_new for row in rows),
        fsrs_learning=sum(row.fsrs_learning for row in rows),
        fsrs_review=sum(row.fsrs_review for row in rows),
        due_count=sum(row.due_count for row in rows),
        words=rows,
    )


def validate_window_days(window_days: int) -> int:
    """校验时间窗取值；非法值 422（可选 7 / 30 / 90 天）。"""
    if window_days not in MASTERY_WINDOW_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"时间窗仅支持 {'/'.join(str(d) for d in MASTERY_WINDOW_DAYS)} 天",
        )
    return window_days


__all__ = [
    "class_vocabulary_mastery",
    "first_try_accuracy",
    "mastery_band",
    "validate_window_days",
]
