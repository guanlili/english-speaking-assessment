"""教师跨任务 / 时间趋势聚合（#517 C）。

口径（与现有班级结果 / 掌握度同事实源，不另造统计口径）：

- 周期：``week``（周一起）/ ``month``（1 日起），时区 ``PRACTICE_TZ``；返回含
  anchor 所在周期在内的最近 N 个周期，按时间升序；区间为闭区间。
- 完成率：分母 = 周期内发布任务的目标名单中**当前在册**学生（手动分组派发按
  实际名单）；完成 = 首轮（round_no=1）首答覆盖全部题位（沿用
  ``progress_of_round1`` 的 done 口径，不要求全对）。
- 首答统计：只取 ``kind=task``、``round_no=1``、``attempt_no=1``，按
  ``answered_at`` 落周期；无作答正确率为 ``null``。
- 掌握度分段：按周期任务快照词条全集逐词聚合全班首答，阈值与现有 mastery
  完全一致（<60 / 60–85 / >85 / 无首答）。
- ``due_unreviewed``：按**当前** ``VocabularyReviewState`` 回算（词 × 能力
  条目数）；历史周期不做状态还原，仅作教学参考。
- 本服务只读，不改写任何 ``snapshot_items`` 或任务快照。
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Student,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularyBookItem,
    VocabularyReviewState,
    VocabularySession,
)
from app.models.vocabulary.reports import (
    VocabularyTrendPeriod,
    VocabularyTrendReport,
)
from app.services import vocabulary as vocab_service
from app.services.vocabulary_mastery import (
    first_try_accuracy,
    mastery_band,
)

GRANULARITY_WEEK = "week"
GRANULARITY_MONTH = "month"
GRANULARITIES = (GRANULARITY_WEEK, GRANULARITY_MONTH)

DEFAULT_PERIODS = 12
MIN_PERIODS = 1
MAX_PERIODS = 24

SESSION_KIND_TASK = "task"
MICROSECOND_END = 999_999


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def _period_dates(
    anchor: date, granularity: str, periods: int
) -> list[tuple[date, date]]:
    """返回闭区间起止日列表（升序），anchor 所在周期为最后一项。"""
    if granularity == GRANULARITY_WEEK:
        monday = anchor - timedelta(days=anchor.weekday())
        starts = [monday - timedelta(weeks=k) for k in range(periods - 1, -1, -1)]
        return [(s, s + timedelta(days=6)) for s in starts]

    # month：从 anchor 所在月向前回溯
    first = anchor.replace(day=1)
    starts: list[date] = []
    cur = first
    for _ in range(periods):
        starts.append(cur)
        prev = cur - timedelta(days=1)
        cur = prev.replace(day=1)
    starts.reverse()
    bounds: list[tuple[date, date]] = []
    for i, start in enumerate(starts):
        if i + 1 < len(starts):
            end = starts[i + 1] - timedelta(days=1)
        else:
            nxt = first + timedelta(days=32)
            end = nxt.replace(day=1) - timedelta(days=1)
        bounds.append((start, end))
    return bounds


def _bounds_utc(start: date, end: date) -> tuple[datetime, datetime]:
    tz = _tz()
    start_dt = datetime.combine(start, time.min, tzinfo=tz)
    end_dt = datetime.combine(
        end, time.max.replace(microsecond=MICROSECOND_END), tzinfo=tz
    )
    return start_dt.astimezone(UTC), end_dt.astimezone(UTC)


def _matches_filters(
    assignment: VocabularyAssignment,
    book_id: uuid.UUID | None,
    prompt_type: str | None,
) -> bool:
    if book_id is not None:
        owned = {str(b) for b in (assignment.source_book_ids or [])}
        if str(book_id) not in owned:
            return False
    if prompt_type is not None:
        if prompt_type not in (assignment.prompt_types or []):
            return False
    return True


def _book_word_ids(session: Session, book_id: uuid.UUID) -> set[uuid.UUID]:
    rows = session.exec(
        select(VocabularyBookItem.word_id).where(
            VocabularyBookItem.book_id == book_id  # type: ignore[arg-type]
        )
    ).all()
    return {word_id for word_id in rows if word_id is not None}


def _snapshot_universe(
    assignments: list[VocabularyAssignment],
    *,
    book_word_ids: set[uuid.UUID] | None,
    prompt_type: str | None,
) -> dict[uuid.UUID, str]:
    """周期任务快照词条全集（按 book / prompt_type 同步缩小）。"""
    universe: dict[uuid.UUID, str] = {}
    for assignment in assignments:
        for item in assignment.snapshot_items or []:
            raw_id = item.get("word_id")
            if raw_id is None:
                continue
            try:
                word_id = uuid.UUID(str(raw_id))
            except ValueError:
                continue
            if book_word_ids is not None and word_id not in book_word_ids:
                continue
            if prompt_type is not None:
                item_types_raw = (
                    item.get("prompt_types") or assignment.prompt_types or []
                )
                item_types = (
                    list(item_types_raw) if isinstance(item_types_raw, list) else []
                )
                if prompt_type not in item_types:
                    continue
            universe.setdefault(word_id, str(item.get("headword") or ""))
    return universe


def build_trend_report(
    session: Session,
    *,
    classroom: Any,
    granularity: str,
    periods: int,
    anchor: date | None,
    book_id: uuid.UUID | None,
    prompt_type: str | None,
    now: datetime | None = None,
) -> VocabularyTrendReport:
    """聚合班级跨任务 / 时间趋势；只读，不改写任务快照。"""
    now = now or datetime.now(UTC)
    tz = _tz()
    anchor_date = anchor or now.astimezone(tz).date()

    period_bounds = _period_dates(anchor_date, granularity, periods)
    period_ranges: list[tuple[date, date, datetime, datetime]] = [
        (start, end, *_bounds_utc(start, end)) for start, end in period_bounds
    ]

    # ── 本班任务（历史发布事实，不随后续归档/入班漂移）───────────────
    assignments = list(
        session.exec(
            select(VocabularyAssignment).where(
                VocabularyAssignment.classroom_id == classroom.id  # type: ignore[arg-type]
            )
        ).all()
    )
    filtered = [a for a in assignments if _matches_filters(a, book_id, prompt_type)]

    book_word_ids = _book_word_ids(session, book_id) if book_id is not None else None

    # 当前在册学生：完成率分母只算在册；手动分组名单按发布时固定名单
    in_class_student_ids = {
        student.id
        for student in session.exec(
            select(Student).where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
        ).all()
    }

    # ── 首答（kind=task / round_no=1 / attempt_no=1）按周期分桶 ──────
    answer_rows = session.exec(
        select(VocabularyAnswer)
        .join(
            VocabularySession,
            VocabularySession.id == VocabularyAnswer.session_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularySession.classroom_id == classroom.id,  # type: ignore[arg-type]
            VocabularySession.kind == SESSION_KIND_TASK,
            VocabularySession.round_no == 1,
            VocabularyAnswer.attempt_no == 1,
        )
    ).all()
    if prompt_type is not None:
        answer_rows = [a for a in answer_rows if a.prompt_type == prompt_type]
    if book_word_ids is not None:
        answer_rows = [a for a in answer_rows if a.word_id in book_word_ids]

    # ── 复习状态（当前快照回算）─────────────────────────────────────
    member_user_ids = [
        student.user_id
        for student in session.exec(
            select(Student).where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
        ).all()
        if student.user_id is not None
    ]

    items: list[VocabularyTrendPeriod] = []
    for start, end, start_utc, end_utc in period_ranges:
        period_assignments = [
            a
            for a in filtered
            if a.published_at is not None and start_utc <= a.published_at <= end_utc
        ]
        period_assignment_ids = [a.id for a in period_assignments]

        # ── 目标数 / 完成数 ──
        targets: list[VocabularyAssignmentTarget] = []
        if period_assignment_ids:
            targets = list(
                session.exec(
                    select(VocabularyAssignmentTarget).where(
                        col(VocabularyAssignmentTarget.assignment_id).in_(  # type: ignore[operator]
                            period_assignment_ids
                        )
                    )
                ).all()
            )
        targets = [t for t in targets if t.student_id in in_class_student_ids]
        assigned = len(targets)

        completed = 0
        if period_assignment_ids:
            rounds_by_assignment = vocab_service._load_classroom_rounds(
                session, classroom.id, period_assignment_ids
            )
            first_round_ids: list[uuid.UUID] = []
            min_by_assignment: dict[uuid.UUID, dict[uuid.UUID, VocabularySession]] = {}
            for aid, rounds in rounds_by_assignment.items():
                by_student = vocab_service._min_round_by_student(rounds)
                min_by_assignment[aid] = by_student
                first_round_ids.extend(session.id for session in by_student.values())
            firsts = vocab_service.first_answers_by_session(session, first_round_ids)

            targets_by_assignment: dict[uuid.UUID, set[uuid.UUID]] = {}
            for target in targets:
                targets_by_assignment.setdefault(target.assignment_id, set()).add(
                    target.student_id
                )
            for assignment in period_assignments:
                total = len(assignment.snapshot_items or [])
                for student_id in targets_by_assignment.get(assignment.id, set()):
                    first_session = min_by_assignment.get(assignment.id, {}).get(
                        student_id
                    )
                    item_firsts = (
                        firsts.get(first_session.id, {}) if first_session else {}
                    )
                    if (
                        vocab_service.progress_of_round1(total, item_firsts)
                        == "completed"
                    ):
                        completed += 1

        completion_rate = round(completed / assigned * 100) if assigned > 0 else None

        # ── 首答聚合 ──
        period_answers = [
            a
            for a in answer_rows
            if a.answered_at is not None and start_utc <= a.answered_at <= end_utc
        ]
        first_answered = len(period_answers)
        first_correct = sum(1 for a in period_answers if a.is_correct)
        first_accuracy = first_try_accuracy(first_correct, first_answered)

        # ── 掌握度分段（周期快照词条全集 × 全班首答）──
        universe = _snapshot_universe(
            period_assignments,
            book_word_ids=book_word_ids,
            prompt_type=prompt_type,
        )
        stats: dict[uuid.UUID, dict[str, int]] = {}
        for answer in period_answers:
            bucket = stats.setdefault(answer.word_id, {"answered": 0, "correct": 0})
            bucket["answered"] += 1
            if answer.is_correct:
                bucket["correct"] += 1

        low = mid = high = no_data = 0
        for word_id in universe:
            bucket = stats.get(word_id)
            answered = bucket["answered"] if bucket else 0
            correct = bucket["correct"] if bucket else 0
            _, band = mastery_band(correct, answered)
            if band == "low":
                low += 1
            elif band == "mid":
                mid += 1
            elif band == "high":
                high += 1
            else:
                no_data += 1

        # ── 到期未复习（当前状态回算，历史周期仅教学参考）──
        due_unreviewed = 0
        if member_user_ids and universe:
            states = session.exec(
                select(VocabularyReviewState).where(
                    col(VocabularyReviewState.user_id).in_(member_user_ids),  # type: ignore[operator]
                    col(VocabularyReviewState.word_id).in_(list(universe.keys())),  # type: ignore[operator]
                    VocabularyReviewState.due_at <= end_utc,  # type: ignore[operator]
                )
            ).all()
            due_unreviewed = len(states)

        items.append(
            VocabularyTrendPeriod(
                period_start=start,
                period_end=end,
                assigned_targets=assigned,
                completed_targets=completed,
                completion_rate=completion_rate,
                first_answered=first_answered,
                first_correct=first_correct,
                first_accuracy=first_accuracy,
                low_count=low,
                mid_count=mid,
                high_count=high,
                no_data_count=no_data,
                due_unreviewed=due_unreviewed,
            )
        )

    return VocabularyTrendReport(
        classroom_code=classroom.code,
        granularity=granularity,
        periods=periods,
        anchor=anchor_date if anchor is not None else None,
        generated_at=now,
        book_id=book_id,
        prompt_type=prompt_type,
        teaching_reference=True,
        items=items,
    )
