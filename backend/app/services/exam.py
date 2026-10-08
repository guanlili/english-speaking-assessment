"""模考域逻辑：整场/逐题限时、每题一次作答、防切屏计数与离屏时长。

时间口径全部以服务器为准（学生端倒计时只是展示）；开考由学生在确认页
显式触发（防误触打开即烧时间）；到时采用惰性终结——任何读写在触碰考试
会话时发现超时即落 exam_ended_at，此后拒绝继续作答。逐题时间由发布
快照、开考时间和首答时间恢复，跳过未答题也不会因刷新而重置。
"""

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Attempt, ClassroomExercise, ExamStatus, PracticeSession

# 题目到时立即推进；仅允许截止前录完的音频有短暂传输时间。
UPLOAD_GRACE_SECONDS = 15


@dataclass(frozen=True)
class ExamItemWindow:
    item_id: uuid.UUID
    item_type: str
    prep_deadline: datetime
    deadline: datetime
    submitted: bool
    finished_at: datetime


def _seconds(value: object, fallback: int) -> int:
    try:
        seconds = int(str(value))
    except ValueError, TypeError:
        return fallback
    return min(300, seconds) if seconds >= 1 else fallback


def item_windows(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> list[ExamItemWindow]:
    """从不可变快照和首答时间恢复题序，不因刷新或评分耗时重置。

    提前提交即开始下一题；未答题到期后按原截止时间推进。
    queued/failed 都是已提交的一次作答，不等待评分，也不能重答。
    """
    cursor = practice_session.exam_started_at
    if cursor is None:
        return []
    attempts = db.exec(
        select(Attempt).where(Attempt.session_id == practice_session.id)
    ).all()
    first_submitted: dict[tuple[str, uuid.UUID], datetime] = {}
    for attempt in attempts:
        if attempt.created_at is not None:
            key = (attempt.item_type, attempt.item_id)
            first_submitted[key] = min(
                first_submitted.get(key, attempt.created_at), attempt.created_at
            )
    windows = []
    for item in exercise.snapshot_items:
        item_type = str(item.get("type", ""))
        text = item.get("text")
        if (
            item_type not in {"passage", "repeat", "question"}
            or not isinstance(text, str)
            or not text.strip()
        ):
            continue
        try:
            item_id = uuid.UUID(str(item.get("id")))
        except ValueError:
            continue
        prep = (
            _seconds(item.get("prep_seconds"), 60)
            if item.get("exam_kind") == "ielts_p2"
            else 0
        )
        prep_deadline = cursor + timedelta(seconds=prep)
        deadline = prep_deadline + timedelta(
            seconds=_seconds(item.get("suggested_seconds"), 20)
        )
        submitted_at = first_submitted.get((item_type, item_id))
        finished_at = (
            max(cursor, min(submitted_at, deadline))
            if submitted_at is not None
            else deadline
        )
        windows.append(
            ExamItemWindow(
                item_id,
                item_type,
                prep_deadline,
                deadline,
                submitted_at is not None,
                finished_at,
            )
        )
        cursor = finished_at
    return windows


def require_current_item(
    db: Session,
    practice_session: PracticeSession,
    exercise: ClassroomExercise,
    item_type: str,
    item_id: uuid.UUID,
) -> None:
    windows = item_windows(db, practice_session, exercise)
    now = _now()
    index = next(
        (
            i
            for i, window in enumerate(windows)
            if not window.submitted and now < window.deadline
        ),
        len(windows),
    )
    # 只给刚到时的上一题留上传窗口，不能回到更早的题或提前答后面的题。
    for candidate in (index, index - 1):
        if candidate < 0 or candidate >= len(windows):
            continue
        window = windows[candidate]
        if (window.item_type, window.item_id) != (
            item_type,
            item_id,
        ) or window.submitted:
            continue
        if (
            window.prep_deadline
            <= now
            <= window.deadline + timedelta(seconds=UPLOAD_GRACE_SECONDS)
        ):
            return
    raise HTTPException(status_code=422, detail="本题作答时间已结束或尚未开始")


def _now() -> datetime:
    return datetime.now(UTC)


def exam_deadline(
    practice_session: PracticeSession, exercise: ClassroomExercise
) -> datetime | None:
    if not exercise.is_exam or practice_session.exam_started_at is None:
        return None
    minutes = exercise.time_limit_minutes or 0
    return practice_session.exam_started_at + timedelta(minutes=minutes)


def ensure_exam_started(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> None:
    """学生在开考确认页点「开始考试」即开始计时；只落一次（幂等）。"""
    if not exercise.is_exam or practice_session.exam_started_at is not None:
        return
    practice_session.exam_started_at = _now()
    db.add(practice_session)
    db.commit()
    db.refresh(practice_session)


def finalize_if_expired(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> bool:
    """到时惰性终结：返回 True 表示本次调用终结了会话（刚到时）。"""
    if not exercise.is_exam or practice_session.exam_ended_at is not None:
        return False
    deadline = exam_deadline(practice_session, exercise)
    if deadline is None:
        return False
    now = _now()
    end = deadline if now >= deadline else None
    windows = item_windows(db, practice_session, exercise)
    if windows and all(
        window.submitted or now >= window.deadline for window in windows
    ):
        last = windows[-1]
        if last.submitted or now >= last.deadline + timedelta(
            seconds=UPLOAD_GRACE_SECONDS
        ):
            end = min(deadline, last.finished_at)
    if end is None:
        return False
    practice_session.exam_ended_at = end
    db.add(practice_session)
    db.commit()
    return True


def exam_remaining_seconds(
    practice_session: PracticeSession, exercise: ClassroomExercise
) -> int:
    deadline = exam_deadline(practice_session, exercise)
    if deadline is None:
        # 确认页尚未开考。
        return (exercise.time_limit_minutes or 0) * 60
    return max(0, int((deadline - _now()).total_seconds()))


def exam_status_payload(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> ExamStatus:
    windows = item_windows(db, practice_session, exercise)
    now = _now()
    index = next(
        (
            i
            for i, window in enumerate(windows)
            if not window.submitted and now < window.deadline
        ),
        len(windows),
    )
    window = windows[index] if index < len(windows) else None
    items_finished = practice_session.exam_started_at is not None and window is None
    return ExamStatus(
        time_limit_minutes=exercise.time_limit_minutes or 0,
        remaining_seconds=0
        if practice_session.exam_ended_at is not None or items_finished
        else exam_remaining_seconds(practice_session, exercise),
        started=practice_session.exam_started_at is not None,
        ended=practice_session.exam_ended_at is not None or items_finished,
        tab_switch_count=practice_session.tab_switch_count,
        current_item_index=index,
        item_remaining_seconds=max(
            0, math.ceil((window.deadline - now).total_seconds())
        )
        if window
        else 0,
        prep_remaining_seconds=max(
            0, math.ceil((window.prep_deadline - now).total_seconds())
        )
        if window
        else 0,
    )


def exam_time_used_seconds(practice_session: PracticeSession) -> int | None:
    """教师端展示口径：开始后计时，交卷/到时为止。"""
    started = practice_session.exam_started_at
    if started is None:
        return None
    end = practice_session.exam_ended_at or _now()
    return max(0, int((end - started).total_seconds()))


def require_exam_open(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> None:
    """作答前的考试门禁：未开考/已到时一律拒绝（服务端强约束）。"""
    if not exercise.is_exam:
        return
    if practice_session.exam_started_at is None:
        # 开考必须经确认页显式触发（POST /exam/start），防止误触打开即计时
        raise HTTPException(status_code=422, detail="考试尚未开始")
    finalize_if_expired(db, practice_session, exercise)
    if practice_session.exam_ended_at is not None:
        raise HTTPException(status_code=422, detail="考试时间已到，已自动交卷")


def _ensure_switch_open(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> None:
    """切屏上报前置：未开考/已结束一律不再累计。"""
    if practice_session.exam_started_at is None:
        raise HTTPException(status_code=422, detail="考试尚未开始")
    finalize_if_expired(db, practice_session, exercise)
    if practice_session.exam_ended_at is not None:
        raise HTTPException(status_code=422, detail="考试已结束")


def record_tab_switch(
    db: Session, practice_session: PracticeSession, exercise: ClassroomExercise
) -> int:
    """前端切屏上报（hidden 相位）：计数并返回最新值（封顶防刷）。"""
    _ensure_switch_open(db, practice_session, exercise)
    practice_session.tab_switch_count = min(999, practice_session.tab_switch_count + 1)
    db.add(practice_session)
    db.commit()
    return practice_session.tab_switch_count


def record_tab_return(
    db: Session,
    practice_session: PracticeSession,
    exercise: ClassroomExercise,
    away_seconds: int,
) -> tuple[int, int]:
    """前端切回上报（visible 相位）：累计离屏时长，返回最新（次数, 秒）。

    单次封顶 1 小时、累计封顶 1 天，负数按 0 计，防异常值刷爆。
    """
    _ensure_switch_open(db, practice_session, exercise)
    practice_session.tab_switch_seconds = min(
        86400,
        practice_session.tab_switch_seconds + max(0, min(away_seconds, 3600)),
    )
    db.add(practice_session)
    db.commit()
    return practice_session.tab_switch_count, practice_session.tab_switch_seconds
