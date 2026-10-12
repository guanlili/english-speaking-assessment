"""Persistent automated exam phases; reading state never restarts a clock."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    ClassroomExercise,
    ExamItemSettings,
    ExamStatus,
    InstructionAck,
    PracticeSession,
)


@dataclass(frozen=True)
class FlowPhase:
    index: int
    item: dict[str, object] | None
    phase: str
    started_at: datetime | None = None
    deadline: datetime | None = None
    answer_start: datetime | None = None
    answer_deadline: datetime | None = None


def enabled(exercise: ClassroomExercise | None) -> bool:
    return bool(
        exercise
        and exercise.is_exam
        and exercise.snapshot_items
        and all(
            isinstance(item.get("exam_flow"), dict) for item in exercise.snapshot_items
        )
    )


def current_phase(
    ps: PracticeSession, exercise: ClassroomExercise, now: datetime
) -> FlowPhase:
    if ps.exam_started_at is None:
        return FlowPhase(0, exercise.snapshot_items[0], "not_started")
    state = ps.exam_flow_state or {}
    for index, item in enumerate(exercise.snapshot_items):
        entry = state.get(str(index), {})
        if entry.get("next_at"):
            continue
        started = (
            datetime.fromisoformat(entry["started_at"])
            if entry.get("started_at")
            else ps.exam_started_at
        )
        settings = ExamItemSettings.model_validate(item["exam_flow"])
        audio_start = started + timedelta(seconds=settings.wait_seconds)
        # 说明题跳过朗读（audio_ended_at 提前写入）后不再停留 waiting
        if now < audio_start and not entry.get("audio_ended_at"):
            return FlowPhase(index, item, "waiting", started, audio_start)
        if item["type"] != "passage":
            if not entry.get("audio_ended_at"):
                return FlowPhase(index, item, "audio", audio_start)
            audio_end = datetime.fromisoformat(entry["audio_ended_at"])
            if item["type"] == "instruction":
                return FlowPhase(index, item, "ready", audio_end)
            prep_end = audio_end + timedelta(
                seconds=(settings.prep_seconds or 0)
                if item["type"] == "question"
                else 0
            )
            if now < prep_end:
                return FlowPhase(index, item, "preparing", audio_end, prep_end)
            answer_start = prep_end + timedelta(seconds=settings.after_audio_seconds)
            if now < answer_start:
                return FlowPhase(index, item, "buffer", prep_end, answer_start)
        else:
            answer_start = audio_start
        answer_deadline = answer_start + timedelta(
            seconds=int(str(item["suggested_seconds"]))
        )
        return FlowPhase(
            index,
            item,
            "answering" if now < answer_deadline else "ready",
            answer_start,
            answer_deadline,
            answer_start,
            answer_deadline,
        )
    return FlowPhase(len(exercise.snapshot_items), None, "finished")


def ended(ps: PracticeSession, exercise: ClassroomExercise, now: datetime) -> bool:
    if ps.exam_ended_at is not None:
        return True
    if ps.exam_started_at is None:
        return False
    return (
        now >= ps.exam_started_at + timedelta(minutes=exercise.time_limit_minutes or 0)
        or current_phase(ps, exercise, now).phase == "finished"
    )


def uploads_allowed(
    ps: PracticeSession,
    exercise: ClassroomExercise,
    now: datetime,
    grace_seconds: int,
) -> bool:
    """上传门禁：整场截止前保持可提交；学生主动提前交卷只保留固定补传窗口。

    与 ended() 的区别：末题 Next 落 exam_ended_at 后，本题录音在
    next_at + grace 内（且不晚于整场截止）仍可首次提交。
    """
    if ps.exam_started_at is None:
        return False
    # 截止边界与 ended() 对齐：恰好到达整场截止即视为结束，不再接受首次提交
    if now >= ps.exam_started_at + timedelta(minutes=exercise.time_limit_minutes or 0):
        return False
    if ps.exam_ended_at is None:
        return True
    finishes = [
        datetime.fromisoformat(entry["next_at"])
        for entry in (ps.exam_flow_state or {}).values()
        if entry.get("next_at")
    ]
    # exam_ended_at 只在末题 Next 时写入，此时 next_at 必然存在
    return bool(finishes) and now <= max(finishes) + timedelta(seconds=grace_seconds)


def status(
    ps: PracticeSession, exercise: ClassroomExercise, now: datetime
) -> ExamStatus:
    phase = current_phase(ps, exercise, now)
    done = ended(ps, exercise, now)
    deadline = (
        ps.exam_started_at + timedelta(minutes=exercise.time_limit_minutes or 0)
        if ps.exam_started_at
        else None
    )
    remaining = (
        max(0, int((deadline - now).total_seconds()))
        if deadline
        else (exercise.time_limit_minutes or 0) * 60
    )
    phase_remaining = (
        max(0, int((phase.deadline - now).total_seconds() + 0.999))
        if phase.deadline
        else 0
    )
    return ExamStatus(
        automated=True,
        phase="finished" if done else phase.phase,
        phase_remaining_seconds=phase_remaining,
        phase_elapsed_seconds=max(0, int((now - phase.started_at).total_seconds()))
        if phase.started_at
        else 0,
        time_limit_minutes=exercise.time_limit_minutes or 0,
        remaining_seconds=0 if done else remaining,
        started=ps.exam_started_at is not None,
        ended=done,
        tab_switch_count=ps.tab_switch_count,
        current_item_index=phase.index,
        item_remaining_seconds=phase_remaining if phase.phase == "answering" else 0,
        prep_remaining_seconds=phase_remaining if phase.phase == "preparing" else 0,
    )


def require_submission(
    _db: Session,
    ps: PracticeSession,
    exercise: ClassroomExercise,
    item_type: str,
    item_id: uuid.UUID,
    now: datetime,
    grace_seconds: int,
) -> None:
    phase = current_phase(ps, exercise, now)
    if ps.exam_started_at is None:
        raise HTTPException(status_code=422, detail="考试尚未开始")
    state = ps.exam_flow_state or {}
    for index in (phase.index, phase.index - 1):
        if index < 0 or index >= len(exercise.snapshot_items):
            continue
        item = exercise.snapshot_items[index]
        if str(item["id"]) != str(item_id) or item["type"] != item_type:
            continue
        # Reconstruct a just-finished item's fixed clock after Next was tapped.
        entry = dict(state.get(str(index), {}))
        entry.pop("next_at", None)
        probe = ps.model_copy(update={"exam_flow_state": {**state, str(index): entry}})
        window = current_phase(probe, exercise, now)
        next_at = (state.get(str(index)) or {}).get("next_at")
        # Retained recordings remain uploadable until Next closes this item.
        upload_deadline = (
            datetime.fromisoformat(next_at) + timedelta(seconds=grace_seconds)
            if next_at
            else ps.exam_started_at
            + timedelta(minutes=exercise.time_limit_minutes or 0)
        )
        if (
            window.answer_start is not None
            and window.answer_start <= now <= upload_deadline
        ):
            return
    raise HTTPException(status_code=422, detail="本题作答时间已结束或尚未开始")


def apply_event(
    db: Session,
    ps: PracticeSession,
    exercise: ClassroomExercise,
    item_id: uuid.UUID,
    event: str,
    now: datetime,
) -> None:
    # Serialize playback acknowledgements and Next across tabs and retries.
    db.exec(
        select(PracticeSession)
        .where(PracticeSession.id == ps.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    state = {key: dict(value) for key, value in (ps.exam_flow_state or {}).items()}
    item_index = next(
        (
            i
            for i, item in enumerate(exercise.snapshot_items)
            if str(item["id"]) == str(item_id)
        ),
        None,
    )
    if item_index is None:
        raise HTTPException(status_code=404, detail="Item not found")
    entry = state.get(str(item_index), {})
    if (event == "next" and entry.get("next_at")) or (
        event == "audio-ended" and entry.get("audio_ended_at")
    ):
        return
    if ended(ps, exercise, now) or ps.exam_started_at is None:
        raise HTTPException(status_code=422, detail="考试时间已到，已自动交卷")
    phase = current_phase(ps, exercise, now)
    if phase.index != item_index:
        raise HTTPException(status_code=422, detail="本题作答时间已结束或尚未开始")
    entry.setdefault(
        "started_at",
        (
            ps.exam_started_at
            if item_index == 0
            else phase.started_at or ps.exam_started_at
        ).isoformat(),
    )
    if event == "audio-ended":
        # 说明题的等待与朗读只是阅读辅助：学生读得快可提前确认（跳过朗读）；
        # 作答题的题干音频是作答依据，仍只能在实际播放阶段确认播完
        kind = exercise.snapshot_items[item_index]["type"]
        allowed = ("waiting", "audio") if kind == "instruction" else ("audio",)
        if phase.phase not in allowed:
            raise HTTPException(status_code=422, detail="Exam audio is not active")
        entry["audio_ended_at"] = now.isoformat()
    elif event == "next":
        # answering 中允许提前交题：说得快的学生说完即走，
        # 麦克风不再收周围同学的说话声（录音先上传、再推进由前端保证）
        if phase.phase not in ("ready", "answering"):
            raise HTTPException(status_code=422, detail="Exam item is not finished")
        entry["next_at"] = now.isoformat()
        if exercise.snapshot_items[item_index]["type"] == "instruction":
            db.add(
                InstructionAck(
                    student_id=ps.student_id,
                    session_id=ps.id,
                    item_id=item_id,
                    created_at=now,
                )
            )
        if item_index + 1 < len(exercise.snapshot_items):
            state[str(item_index + 1)] = {"started_at": now.isoformat()}
        else:
            ps.exam_ended_at = now
    else:
        raise HTTPException(status_code=422, detail="Invalid exam event")
    state[str(item_index)] = entry
    ps.exam_flow_state = state
    db.add(ps)
    db.commit()
