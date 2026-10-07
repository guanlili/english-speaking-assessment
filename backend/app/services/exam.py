"""模考域逻辑：整场限时、每题一次作答、防切屏计数与离屏时长。

时间口径全部以服务器为准（学生端倒计时只是展示）；开考由学生在确认页
显式触发（防误触打开即烧时间）；到时采用惰性终结——任何读写在触碰考试
会话时发现超时即落 exam_ended_at，此后拒绝继续作答。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from app.models import ClassroomExercise, ExamStatus, PracticeSession


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
    db: Any, practice_session: PracticeSession, exercise: ClassroomExercise
) -> None:
    """学生在开考确认页点「开始考试」即开始计时；只落一次（幂等）。"""
    if not exercise.is_exam or practice_session.exam_started_at is not None:
        return
    practice_session.exam_started_at = _now()
    db.add(practice_session)
    db.commit()
    db.refresh(practice_session)


def finalize_if_expired(
    db: Any, practice_session: PracticeSession, exercise: ClassroomExercise
) -> bool:
    """到时惰性终结：返回 True 表示本次调用终结了会话（刚到时）。"""
    if not exercise.is_exam or practice_session.exam_ended_at is not None:
        return False
    deadline = exam_deadline(practice_session, exercise)
    if deadline is None or _now() <= deadline:
        return False
    practice_session.exam_ended_at = _now()
    db.add(practice_session)
    db.commit()
    return True


def exam_remaining_seconds(
    practice_session: PracticeSession, exercise: ClassroomExercise
) -> int:
    deadline = exam_deadline(practice_session, exercise)
    if deadline is None:
        # 未开始计时（理论不可达：today 会先落开始时间）
        return (exercise.time_limit_minutes or 0) * 60
    return max(0, int((deadline - _now()).total_seconds()))


def exam_status_payload(
    practice_session: PracticeSession, exercise: ClassroomExercise
) -> ExamStatus:
    return ExamStatus(
        time_limit_minutes=exercise.time_limit_minutes or 0,
        remaining_seconds=exam_remaining_seconds(practice_session, exercise),
        started=practice_session.exam_started_at is not None,
        ended=practice_session.exam_ended_at is not None,
        tab_switch_count=practice_session.tab_switch_count,
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
