"""Teaching actions: short-lived presence, diagnostic recipient selection and reports."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal, cast
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query
from sqlalchemy.orm import load_only
from sqlmodel import SQLModel, col, select

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.class_shared import (
    _get_classroom,
    _get_student_of_classroom,
    _require_classroom_teacher,
    _student_profile_of,
    _today_in_practice_tz,
    router,
)
from app.core.config import settings
from app.models import (
    Attempt,
    ClassroomExercise,
    PracticeSession,
    Student,
    get_datetime_utc,
)
from app.scoring.heuristic import tokenize
from app.services import exam as exam_service
from app.services.class_gaps import LOW_OVERALL, missed_content_words

PRESENCE_TTL = 90
SHORT_ANSWER_WORDS = 15
DEVICE_CHECK_TTL_HOURS = 2
REPORT_ANSWER_LIMIT = 6


class ClassroomActivityIn(SQLModel):
    activity: Literal["entered", "recording", "uploading", "idle"] = "entered"
    session_id: uuid.UUID | None = None
    device_check: Literal["passed", "failed"] | None = None


class ClassroomPresence(SQLModel):
    student_id: uuid.UUID
    display_name: str
    activity: Literal["entered", "recording", "uploading", "idle", "unknown"]
    observed_at: datetime | None = None
    device_check: Literal["passed", "failed"] | None = None
    device_checked_at: datetime | None = None


def recent_time(value: object, cutoff: datetime) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None and parsed >= cutoff else None
    except ValueError:
        return None


@router.put("/{code}/activity", response_model=None)
def report_classroom_activity(
    session: SessionDep,
    code: str,
    body: ClassroomActivityIn,
    current_user: StudentUserDep,
) -> None:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    exercise_id = classroom.current_exercise_id
    if body.session_id is not None:
        ps = session.get(PracticeSession, body.session_id)
        if ps is None or ps.student_id != student.id or ps.classroom_id != classroom.id:
            raise HTTPException(404, detail="Session not found")
        exercise_id = ps.assignment_id
    # Lock only the short update; keep device results when heartbeat arrives.
    session.refresh(student, with_for_update=True)
    state = dict(student.classroom_activity or {})
    now = get_datetime_utc().isoformat()
    state.update(activity=body.activity, observed_at=now, exercise_id=str(exercise_id))
    if body.device_check is not None:
        state.update(device_check=body.device_check, device_checked_at=now)
    student.classroom_activity = state
    session.add(student)
    session.commit()


@router.get("/{code}/presence", response_model=list[ClassroomPresence])
def read_classroom_presence(
    session: SessionDep, code: str, current_user: CurrentUser
) -> list[ClassroomPresence]:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    now = get_datetime_utc()
    result = []
    for student in session.exec(
        select(Student).where(Student.classroom_id == classroom.id)
    ).all():
        state = student.classroom_activity or {}
        seen = recent_time(
            state.get("observed_at"), now - timedelta(seconds=PRESENCE_TTL)
        )
        if state.get("exercise_id") != str(classroom.current_exercise_id):
            seen = None
        activity = state.get("activity") if seen else "unknown"
        checked = recent_time(
            state.get("device_checked_at"),
            now - timedelta(hours=DEVICE_CHECK_TTL_HOURS),
        )
        device = state.get("device_check") if checked else None
        result.append(
            ClassroomPresence(
                student_id=student.id,
                display_name=student.display_name
                + (f"·{student.suffix}" if student.suffix else ""),
                activity=cast(
                    Literal["entered", "recording", "uploading", "idle"], activity
                )
                if activity in ("entered", "recording", "uploading", "idle")
                else "unknown",
                observed_at=seen,
                device_check=cast(Literal["passed", "failed"], device)
                if device in ("passed", "failed")
                else None,
                device_checked_at=checked,
            )
        )
    return result


class DiagnosticStudentItems(SQLModel):
    student_id: uuid.UUID
    item_ids: list[uuid.UUID]


class DiagnosticTargets(SQLModel):
    source_exercise_id: uuid.UUID
    student_ids: list[uuid.UUID]
    item_ids: list[uuid.UUID]
    matched_answers: int
    targets: list[DiagnosticStudentItems] = []


@router.get("/{code}/diagnostic-targets", response_model=DiagnosticTargets)
def read_diagnostic_targets(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    rule: Literal["low_score", "short_answer", "missed_word", "teacher_focus"],
    word: str = Query(default="", max_length=100),
    item_id: uuid.UUID | None = None,
) -> DiagnosticTargets:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    source = (
        session.get(ClassroomExercise, classroom.current_exercise_id)
        if classroom.current_exercise_id
        else None
    )
    if source is None:
        raise HTTPException(404, detail="Exercise not found")
    if source.is_exam:
        raise HTTPException(409, detail="Active exam cannot be assigned as followup")
    rows = session.exec(
        select(Attempt)
        .join(PracticeSession, col(Attempt.session_id) == col(PracticeSession.id))
        .join(Student, col(Attempt.student_id) == col(Student.id))
        .where(
            PracticeSession.classroom_id == classroom.id,
            PracticeSession.assignment_id == source.id,
            PracticeSession.session_date == _today_in_practice_tz(),
            PracticeSession.mode == "daily",
            Student.classroom_id == classroom.id,
        )
        .options(
            # 课上高频刷新：只取判定用的小列，rubric/word_alignment 大 JSON 不进内存
            load_only(
                Attempt.id,  # ty: ignore[invalid-argument-type]
                Attempt.student_id,  # ty: ignore[invalid-argument-type]
                Attempt.item_id,  # ty: ignore[invalid-argument-type]
                Attempt.item_type,  # ty: ignore[invalid-argument-type]
                Attempt.status,  # ty: ignore[invalid-argument-type]
                Attempt.overall,  # ty: ignore[invalid-argument-type]
                Attempt.transcript,  # ty: ignore[invalid-argument-type]
                Attempt.item_snapshot,  # ty: ignore[invalid-argument-type]
                Attempt.teacher_focus,  # ty: ignore[invalid-argument-type]
                Attempt.created_at,  # ty: ignore[invalid-argument-type]
            )
        )
        .order_by(col(Attempt.created_at), col(Attempt.id))
    ).all()
    latest = {(a.student_id, a.item_id): a for a in rows}
    matches = []
    for a in latest.values():
        if a.status != "done" or (item_id is not None and a.item_id != item_id):
            continue
        reference = str((a.item_snapshot or {}).get("text", ""))
        matched = (
            (rule == "low_score" and a.overall is not None and a.overall < LOW_OVERALL)
            or (
                rule == "short_answer"
                and a.item_type == "question"
                and bool(a.transcript)
                and len(tokenize(a.transcript or "")) < SHORT_ANSWER_WORDS
            )
            or (rule == "teacher_focus" and a.teacher_focus)
            or (
                rule == "missed_word"
                and a.item_type in ("passage", "repeat")
                and bool(word.strip())
                and word.strip().lower()
                in missed_content_words(reference, a.transcript or "")
            )
        )
        if matched:
            matches.append(a)
    return DiagnosticTargets(
        source_exercise_id=source.id,
        student_ids=sorted({a.student_id for a in matches if a.student_id}, key=str),
        item_ids=sorted({a.item_id for a in matches}, key=str),
        matched_answers=len(matches),
        targets=[
            DiagnosticStudentItems(
                student_id=sid,
                item_ids=sorted(
                    {a.item_id for a in matches if a.student_id == sid}, key=str
                ),
            )
            for sid in sorted({a.student_id for a in matches if a.student_id}, key=str)
        ],
    )


class ReportAnswer(SQLModel):
    attempt_id: uuid.UUID
    item_type: str
    item_text: str | None
    teacher_feedback: str | None
    teacher_review_tags: list[str] | None
    created_at: datetime | None


class LearningReport(SQLModel):
    display_name: str
    start_date: date
    end_date: date
    session_count: int
    completed_items: int
    total_items: int
    speaking_minutes: float
    reading_avg: float | None
    question_avg: float | None
    answers: list[ReportAnswer]
    has_active_exam: bool


@router.get("/{code}/learning-report", response_model=LearningReport)
def read_learning_report(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    days: int = Query(default=7, ge=1, le=90),
    student_id: uuid.UUID | None = None,
    exercise_id: uuid.UUID | None = None,
) -> LearningReport:
    classroom = _get_classroom(session, code)
    if current_user.role == "student":
        student = _student_profile_of(session, classroom, current_user)
        if student_id is not None and student_id != student.id:
            raise HTTPException(403, detail="No permission")
    else:
        _require_classroom_teacher(classroom, current_user)
        if student_id is None:
            raise HTTPException(422, detail="Student required")
        student = _get_student_of_classroom(session, classroom, student_id)
    end = _today_in_practice_tz()
    start = end - timedelta(days=days - 1)
    sessions = session.exec(
        select(PracticeSession).where(
            PracticeSession.classroom_id == classroom.id,
            PracticeSession.student_id == student.id,
            PracticeSession.session_date >= start,
            PracticeSession.session_date <= end,
        )
    ).all()
    if exercise_id is not None:
        sessions = [ps for ps in sessions if ps.assignment_id == exercise_id]
    exercises = (
        {
            e.id: e
            for e in session.exec(
                select(ClassroomExercise).where(
                    col(ClassroomExercise.id).in_(
                        {ps.assignment_id for ps in sessions if ps.assignment_id}
                    )
                )
            ).all()
        }
        if sessions
        else {}
    )
    visible = []
    total = 0
    active = False
    # 旧式（无 exam_flow）考试的遮罩判定需要首答时间：批量预取，避免
    # 循环内逐会话查询（N+1）
    first = exam_service.first_submitted_by_session(
        session,
        [
            ps.id
            for ps in sessions
            if (ex := exercises.get(ps.assignment_id) if ps.assignment_id else None)
            is not None
            and ex.is_exam
        ],
    )
    for ps in sessions:
        exercise = exercises.get(ps.assignment_id) if ps.assignment_id else None
        locked = (
            exercise is not None
            and exercise.is_exam
            and exam_service.exam_feedback_locked(
                session, ps, exercise, first_submitted=first.get(ps.id, {})
            )
        )
        # Reports never expose an unfinished exam, even in the teacher preview.
        if locked:
            active = True
            continue
        visible.append(ps.id)
        if exercise:
            total += sum(
                item.get("type") != "instruction" for item in exercise.snapshot_items
            )
    window_start = datetime.combine(start, time.min, ZoneInfo(settings.PRACTICE_TZ))
    window_end = datetime.combine(
        end + timedelta(days=1), time.min, ZoneInfo(settings.PRACTICE_TZ)
    )
    rows = (
        session.exec(
            select(Attempt)
            .where(
                col(Attempt.session_id).in_(visible),
                col(Attempt.created_at) >= window_start,
                col(Attempt.created_at) < window_end,
            )
            .order_by(col(Attempt.created_at), col(Attempt.id))
        ).all()
        if visible
        else []
    )
    latest = {(a.session_id, a.item_id): a for a in rows}
    scored = [a for a in latest.values() if a.status == "done"]

    def average(types: tuple[str, ...]) -> float | None:
        scores = [
            a.overall for a in scored if a.item_type in types and a.overall is not None
        ]
        return round(sum(scores) / len(scores), 1) if scores else None

    representatives = sorted(
        scored,
        key=lambda a: (
            bool(a.teacher_feedback or a.teacher_review_tags),
            a.created_at or window_start,
        ),
        reverse=True,
    )[:REPORT_ANSWER_LIMIT]
    return LearningReport(
        display_name=student.display_name,
        start_date=start,
        end_date=end,
        session_count=len(visible),
        completed_items=len(scored),
        total_items=max(total, len(latest)),
        speaking_minutes=round(sum(a.duration_s for a in rows) / 60, 1),
        reading_avg=average(("passage", "repeat")),
        question_avg=average(("question",)),
        answers=[
            ReportAnswer(
                attempt_id=a.id,
                item_type=a.item_type,
                item_text=str((a.item_snapshot or {}).get("text", "")) or None,
                teacher_feedback=a.teacher_feedback,
                teacher_review_tags=a.teacher_review_tags,
                created_at=a.created_at,
            )
            for a in representatives
        ],
        has_active_exam=active,
    )
