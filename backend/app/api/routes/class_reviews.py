"""Saved discussion notes and explicitly published student-facing summaries."""

import uuid
from datetime import datetime

from fastapi import HTTPException, Query
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
    router,
)
from app.models import ClassroomExercise, ClassroomReview, PracticeSession
from app.services import classroom_review, exam


class ClassReviewPublic(SQLModel):
    revision: int = 0
    notes: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    published_summary: str | None = None
    published_at: datetime | None = None


class ClassReviewWrite(SQLModel):
    expected_revision: int = Field(ge=0)
    attempt_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=4000)
    summary: str | None = Field(default=None, max_length=4000)


class ClassReviewRevision(SQLModel):
    expected_revision: int = Field(ge=0)


class PublishedClassSummary(SQLModel):
    exercise_id: uuid.UUID
    title: str
    text: str
    published_at: datetime


def teacher_exercise(
    session: SessionDep, code: str, exercise_id: uuid.UUID, user: CurrentUser
) -> ClassroomExercise:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, user)
    exercise = session.get(ClassroomExercise, exercise_id)
    if (
        exercise is None
        or exercise.classroom_id != classroom.id
        or exercise.status not in ("published", "archived")
    ):
        raise HTTPException(404, detail="Exercise not found")
    return exercise


@router.get("/{code}/exercises/{exercise_id}/review", response_model=ClassReviewPublic)
def read_class_review(
    session: SessionDep, code: str, exercise_id: uuid.UUID, current_user: CurrentUser
) -> ClassReviewPublic:
    exercise = teacher_exercise(session, code, exercise_id, current_user)
    row = session.get(ClassroomReview, exercise.id)
    return (
        ClassReviewPublic.model_validate(row, from_attributes=True)
        if row
        else ClassReviewPublic()
    )


@router.put("/{code}/exercises/{exercise_id}/review", response_model=ClassReviewPublic)
def save_class_review(
    session: SessionDep,
    code: str,
    exercise_id: uuid.UUID,
    body: ClassReviewWrite,
    current_user: CurrentUser,
) -> ClassReviewPublic:
    exercise = teacher_exercise(session, code, exercise_id, current_user)
    if body.attempt_id is None and body.note is None and body.summary is None:
        raise HTTPException(422, detail="Empty review update")
    row = classroom_review.save_review(
        session,
        exercise,
        body.expected_revision,
        attempt_id=body.attempt_id,
        note=body.note,
        summary=body.summary,
    )
    return ClassReviewPublic.model_validate(row, from_attributes=True)


@router.post(
    "/{code}/exercises/{exercise_id}/review/publish", response_model=ClassReviewPublic
)
def publish_class_review(
    session: SessionDep,
    code: str,
    exercise_id: uuid.UUID,
    body: ClassReviewRevision,
    current_user: CurrentUser,
) -> ClassReviewPublic:
    exercise = teacher_exercise(session, code, exercise_id, current_user)
    return ClassReviewPublic.model_validate(
        classroom_review.save_review(
            session, exercise, body.expected_revision, publish=True
        ),
        from_attributes=True,
    )


@router.post(
    "/{code}/exercises/{exercise_id}/review/withdraw", response_model=ClassReviewPublic
)
def withdraw_class_review(
    session: SessionDep,
    code: str,
    exercise_id: uuid.UUID,
    body: ClassReviewRevision,
    current_user: CurrentUser,
) -> ClassReviewPublic:
    exercise = teacher_exercise(session, code, exercise_id, current_user)
    return ClassReviewPublic.model_validate(
        classroom_review.save_review(
            session, exercise, body.expected_revision, withdraw=True
        ),
        from_attributes=True,
    )


@router.get("/{code}/review-summaries", response_model=list[PublishedClassSummary])
def read_published_class_summaries(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[PublishedClassSummary]:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    blocked = set()
    for ps, exercise in session.exec(
        select(PracticeSession, ClassroomExercise)
        .join(
            ClassroomExercise,
            col(PracticeSession.assignment_id) == col(ClassroomExercise.id),
        )
        .where(
            PracticeSession.student_id == student.id,
            ClassroomExercise.classroom_id == classroom.id,
            col(ClassroomExercise.is_exam).is_(True),
        )
    ).all():
        if exam.exam_feedback_locked(session, ps, exercise):
            blocked.add(exercise.id)
    current = (
        session.get(ClassroomExercise, classroom.current_exercise_id)
        if classroom.current_exercise_id
        else None
    )
    if current and current.is_exam:
        blocked.add(current.id)
    rows = session.exec(
        select(ClassroomReview, ClassroomExercise)
        .join(
            ClassroomExercise,
            col(ClassroomReview.exercise_id) == col(ClassroomExercise.id),
        )
        .where(
            ClassroomReview.classroom_id == classroom.id,
            col(ClassroomReview.published_summary).is_not(None),
            col(ClassroomReview.exercise_id).not_in(blocked),
        )
        .order_by(
            col(ClassroomReview.published_at).desc(), col(ClassroomReview.exercise_id)
        )
        .offset(offset)
        .limit(limit)
    ).all()
    result = []
    for row, exercise in rows:
        if row.published_summary and row.published_at:
            result.append(
                PublishedClassSummary(
                    exercise_id=exercise.id,
                    title=exercise.title,
                    text=row.published_summary,
                    published_at=row.published_at,
                )
            )
    return result
