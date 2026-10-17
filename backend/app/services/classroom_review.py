"""Review drafts remain private until the teacher publishes a class summary."""

import uuid

from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.models import (
    Attempt,
    ClassroomExercise,
    ClassroomReview,
    PracticeSession,
    get_datetime_utc,
)
from app.services import exam


def save_review(
    session: Session,
    exercise: ClassroomExercise,
    revision: int,
    *,
    attempt_id: uuid.UUID | None = None,
    note: str | None = None,
    summary: str | None = None,
    publish: bool = False,
    withdraw: bool = False,
) -> ClassroomReview:
    row = crud.get_classroom_review_for_update(session, exercise)
    if (row.revision if row else 0) != revision:
        raise HTTPException(409, detail="Class review revision conflict")
    if (attempt_id is None) != (note is None):
        raise HTTPException(422, detail="Invalid review note")
    if attempt_id is not None:
        attempt = session.get(Attempt, attempt_id)
        ps = (
            session.get(PracticeSession, attempt.session_id)
            if attempt and attempt.session_id
            else None
        )
        if (
            ps is None
            or ps.classroom_id != exercise.classroom_id
            or ps.assignment_id != exercise.id
        ):
            raise HTTPException(404, detail="Attempt not found")
        if exercise.is_exam and exam.exam_feedback_locked(session, ps, exercise):
            raise HTTPException(422, detail="Exam review unavailable")
    if publish and exercise.is_exam:
        from app.models import Classroom

        classroom = session.get(Classroom, exercise.classroom_id)
        if classroom and classroom.current_exercise_id == exercise.id:
            raise HTTPException(422, detail="Exam review unavailable")
        for ps in session.exec(
            select(PracticeSession).where(PracticeSession.assignment_id == exercise.id)
        ).all():
            if exam.exam_feedback_locked(session, ps, exercise):
                raise HTTPException(422, detail="Exam review unavailable")
    if row is None:
        row = ClassroomReview(
            exercise_id=exercise.id, classroom_id=exercise.classroom_id
        )
    if attempt_id is not None and note is not None:
        notes = dict(row.notes)
        if note.strip():
            notes[str(attempt_id)] = note.strip()
        else:
            notes.pop(str(attempt_id), None)
        row.notes = notes
    if summary is not None:
        row.summary = summary.strip()
    if publish:
        if not row.summary.strip():
            raise HTTPException(422, detail="Empty review summary")
        row.published_summary = row.summary
        row.published_at = get_datetime_utc()
    if withdraw:
        row.published_summary = None
        row.published_at = None
    row.revision += 1
    row.updated_at = get_datetime_utc()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
