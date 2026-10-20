"""Teacher-only, item-matched evidence of a targeted-practice assignment."""

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import load_only
from sqlmodel import Session, SQLModel, col, select

from app.models import Attempt, Classroom, ClassroomExercise, PracticeSession
from app.services import exam


class FollowupEvidence(SQLModel):
    attempt_id: uuid.UUID
    status: str
    engine: str
    overall: int | None
    teacher_feedback: str | None
    teacher_focus: bool
    created_at: datetime | None


class FollowupItemOutcome(SQLModel):
    item_id: uuid.UUID
    text: str
    item_type: str
    original: FollowupEvidence | None
    followup: FollowupEvidence | None
    reference_change: int | None


class FollowupStudentOutcome(SQLModel):
    student_id: uuid.UUID
    display_name: str
    completed_items: int
    total_items: int
    items: list[FollowupItemOutcome]


class FollowupOutcomes(SQLModel):
    task_id: uuid.UUID
    title: str
    source_title: str | None
    assigned_at: datetime | None
    total_students: int
    students: list[FollowupStudentOutcome]


def evidence(attempt: Attempt | None) -> FollowupEvidence | None:
    if attempt is None:
        return None
    return FollowupEvidence(
        attempt_id=attempt.id,
        status=attempt.status,
        engine=attempt.engine,
        overall=attempt.overall if attempt.status == "done" else None,
        teacher_feedback=attempt.teacher_feedback,
        teacher_focus=attempt.teacher_focus,
        created_at=attempt.created_at,
    )


def read_outcomes(
    session: Session,
    classroom: Classroom,
    task: ClassroomExercise,
    offset: int,
    limit: int,
) -> FollowupOutcomes:
    source = (
        session.get(ClassroomExercise, task.source_exercise_id)
        if task.source_exercise_id
        else None
    )
    if source and source.classroom_id != classroom.id:
        raise HTTPException(404, detail="Exercise not found")
    if source and source.is_exam and classroom.current_exercise_id == source.id:
        raise HTTPException(422, detail="Exam outcomes unavailable")
    targets = task.target_students or []
    page = targets[offset : offset + limit]
    student_ids = [uuid.UUID(row["student_id"]) for row in page]
    item_ids = [
        uuid.UUID(str(item["id"]))
        for item in task.snapshot_items
        if item.get("type") != "instruction"
    ]
    before = task.published_at or task.created_at

    def latest(
        assignment_id: uuid.UUID, baseline: bool
    ) -> dict[tuple[uuid.UUID, uuid.UUID], Attempt]:
        statement = (
            select(Attempt)
            .join(PracticeSession, col(Attempt.session_id) == col(PracticeSession.id))
            .where(
                PracticeSession.classroom_id == classroom.id,
                PracticeSession.assignment_id == assignment_id,
                col(PracticeSession.student_id).in_(student_ids),
                col(Attempt.item_id).in_(item_ids),
                Attempt.student_id == PracticeSession.student_id,
            )
        )
        if baseline:
            if before is None:
                return {}
            statement = statement.where(col(Attempt.created_at) <= before)
        # Rank in SQL so repeated attempts never make the response grow unbounded.
        ranked = statement.with_only_columns(
            col(Attempt.id).label("attempt_id"),
            func.row_number()
            .over(
                partition_by=(col(Attempt.student_id), col(Attempt.item_id)),
                order_by=(col(Attempt.created_at).desc(), col(Attempt.id).desc()),
            )
            .label("rank"),
        ).subquery()
        rows = session.exec(
            select(Attempt)
            .options(
                # evidence() 只读小列：transcript/rubric/word_alignment 等大 JSON 不进内存
                load_only(
                    Attempt.id,  # ty: ignore[invalid-argument-type]
                    Attempt.student_id,  # ty: ignore[invalid-argument-type]
                    Attempt.item_id,  # ty: ignore[invalid-argument-type]
                    Attempt.status,  # ty: ignore[invalid-argument-type]
                    Attempt.engine,  # ty: ignore[invalid-argument-type]
                    Attempt.overall,  # ty: ignore[invalid-argument-type]
                    Attempt.teacher_feedback,  # ty: ignore[invalid-argument-type]
                    Attempt.teacher_focus,  # ty: ignore[invalid-argument-type]
                    Attempt.created_at,  # ty: ignore[invalid-argument-type]
                )
            )
            .join(ranked, col(Attempt.id) == ranked.c.attempt_id)
            .where(ranked.c.rank == 1)
        ).all()
        return {(row.student_id, row.item_id): row for row in rows if row.student_id}

    originals = latest(source.id, True) if source else {}
    current = latest(task.id, False)
    locked_students = set()
    if source and source.is_exam:
        exam_sessions = session.exec(
            select(PracticeSession).where(
                PracticeSession.assignment_id == source.id,
                col(PracticeSession.student_id).in_(student_ids),
            )
        ).all()
        # 旧式（无 exam_flow）考试的遮罩判定需要首答时间：一次预取，不逐会话查询
        first = exam.first_submitted_by_session(
            session, [ps.id for ps in exam_sessions]
        )
        for ps in exam_sessions:
            if exam.exam_feedback_locked(
                session, ps, source, first_submitted=first.get(ps.id, {})
            ):
                locked_students.add(ps.student_id)
    rows = []
    for target in page:
        sid = uuid.UUID(target["student_id"])
        items = []
        for item in task.snapshot_items:
            if item.get("type") == "instruction":
                continue
            iid = uuid.UUID(str(item["id"]))
            original = (
                evidence(originals.get((sid, iid)))
                if sid not in locked_students
                else None
            )
            followup = evidence(current.get((sid, iid)))
            change = None
            if (
                original
                and followup
                and original.status == followup.status == "done"
                and original.engine == followup.engine
                and original.overall is not None
                and followup.overall is not None
            ):
                change = followup.overall - original.overall
            items.append(
                FollowupItemOutcome(
                    item_id=iid,
                    text=str(item.get("text", "")),
                    item_type=str(item["type"]),
                    original=original,
                    followup=followup,
                    reference_change=change,
                )
            )
        rows.append(
            FollowupStudentOutcome(
                student_id=sid,
                display_name=target["display_name"],
                completed_items=sum(
                    bool(item.followup and item.followup.status == "done")
                    for item in items
                ),
                total_items=len(items),
                items=items,
            )
        )
    return FollowupOutcomes(
        task_id=task.id,
        title=task.title,
        source_title=source.title if source else None,
        assigned_at=before,
        total_students=len(targets),
        students=rows,
    )
