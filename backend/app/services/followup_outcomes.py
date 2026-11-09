"""Teacher-only, item-matched evidence of a targeted-practice assignment."""

import uuid
from datetime import datetime
from typing import Any

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


def _source_exercise(
    session: Session, classroom: Classroom, task: ClassroomExercise
) -> ClassroomExercise | None:
    """任务指向的源作业；跨校或正在考的单子按原语义拒答。"""
    source = (
        session.get(ClassroomExercise, task.source_exercise_id)
        if task.source_exercise_id
        else None
    )
    if source and source.classroom_id != classroom.id:
        raise HTTPException(404, detail="Exercise not found")
    if source and source.is_exam and classroom.current_exercise_id == source.id:
        raise HTTPException(422, detail="Exam outcomes unavailable")
    return source


def _outcome_item_ids(task: ClassroomExercise) -> list[uuid.UUID]:
    """本任务参与统计的条目 ID（题目说明无作答，排除）。"""
    return [
        uuid.UUID(str(item["id"]))
        for item in task.snapshot_items
        if item.get("type") != "instruction"
    ]


def _outcome_attempt_statement(
    classroom: Classroom,
    assignment_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    item_ids: list[uuid.UUID],
    baseline: bool,
    before: datetime | None,
) -> Any | None:
    """本页学生在这份作业上、这些条目的作答查询。

    baseline 为真时再卡发布时间上界；没有发布时间说明没有基线可比，返回 None。
    """
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
    if not baseline:
        return statement
    if before is None:
        return None
    return statement.where(col(Attempt.created_at) <= before)


def _ranked_latest_attempts(statement: Any) -> Any:
    """按（学生, 条目）打行号：重复作答在 SQL 里就收掉，响应不会无限增长。"""
    return statement.with_only_columns(
        col(Attempt.id).label("attempt_id"),
        func.row_number()
        .over(
            partition_by=(col(Attempt.student_id), col(Attempt.item_id)),
            order_by=(col(Attempt.created_at).desc(), col(Attempt.id).desc()),
        )
        .label("rank"),
    ).subquery()


def _latest_attempts(
    session: Session,
    classroom: Classroom,
    assignment_id: uuid.UUID,
    student_ids: list[uuid.UUID],
    item_ids: list[uuid.UUID],
    *,
    baseline: bool,
    before: datetime | None,
) -> dict[tuple[uuid.UUID, uuid.UUID], Attempt]:
    """(学生, 条目) → 这份作业上最近一次作答。"""
    statement = _outcome_attempt_statement(
        classroom, assignment_id, student_ids, item_ids, baseline, before
    )
    if statement is None:
        return {}
    ranked = _ranked_latest_attempts(statement)
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


def _outcome_attempt_maps(
    session: Session,
    classroom: Classroom,
    task: ClassroomExercise,
    source: ClassroomExercise | None,
    student_ids: list[uuid.UUID],
    item_ids: list[uuid.UUID],
    before: datetime | None,
) -> tuple[
    dict[tuple[uuid.UUID, uuid.UUID], Attempt],
    dict[tuple[uuid.UUID, uuid.UUID], Attempt],
]:
    """基线与追练两张 (学生, 条目) → 最近作答映射。"""
    originals = (
        _latest_attempts(
            session,
            classroom,
            source.id,
            student_ids,
            item_ids,
            baseline=True,
            before=before,
        )
        if source
        else {}
    )
    current = _latest_attempts(
        session,
        classroom,
        task.id,
        student_ids,
        item_ids,
        baseline=False,
        before=None,
    )
    return originals, current


def _locked_students(
    session: Session,
    source: ClassroomExercise | None,
    student_ids: list[uuid.UUID],
) -> set[uuid.UUID]:
    """旧式（无 exam_flow）考试下不展示基线成绩的学生。

    遮罩判定要首答时间：一次预取全部会话，不逐会话查询。
    """
    if source is None or not source.is_exam:
        return set()
    exam_sessions = session.exec(
        select(PracticeSession).where(
            PracticeSession.assignment_id == source.id,
            col(PracticeSession.student_id).in_(student_ids),
        )
    ).all()
    first = exam.first_submitted_by_session(session, [ps.id for ps in exam_sessions])
    return {
        ps.student_id
        for ps in exam_sessions
        if exam.exam_feedback_locked(
            session, ps, source, first_submitted=first.get(ps.id, {})
        )
    }


def _reference_change(
    original: FollowupEvidence | None, followup: FollowupEvidence | None
) -> int | None:
    """同一条目、同一引擎、两边都完成时才有总分变化。"""
    if not (
        original
        and followup
        and original.status == followup.status == "done"
        and original.engine == followup.engine
        and original.overall is not None
        and followup.overall is not None
    ):
        return None
    return followup.overall - original.overall


def _item_outcome(
    item: dict[str, object],
    student_id: uuid.UUID,
    originals: dict[tuple[uuid.UUID, uuid.UUID], Attempt],
    current: dict[tuple[uuid.UUID, uuid.UUID], Attempt],
    locked: bool,
) -> FollowupItemOutcome:
    """单条目的原答 / 追练对照；被遮罩的学生不给基线。"""
    item_id = uuid.UUID(str(item["id"]))
    original = None if locked else evidence(originals.get((student_id, item_id)))
    followup = evidence(current.get((student_id, item_id)))
    return FollowupItemOutcome(
        item_id=item_id,
        text=str(item.get("text", "")),
        item_type=str(item["type"]),
        original=original,
        followup=followup,
        reference_change=_reference_change(original, followup),
    )


def _student_outcome(
    target: dict[str, str],
    task: ClassroomExercise,
    originals: dict[tuple[uuid.UUID, uuid.UUID], Attempt],
    current: dict[tuple[uuid.UUID, uuid.UUID], Attempt],
    locked: set[uuid.UUID],
) -> FollowupStudentOutcome:
    """一个学生的逐条目对照与完成数。"""
    student_id = uuid.UUID(target["student_id"])
    items = [
        _item_outcome(item, student_id, originals, current, student_id in locked)
        for item in task.snapshot_items
        if item.get("type") != "instruction"
    ]
    return FollowupStudentOutcome(
        student_id=student_id,
        display_name=target["display_name"],
        completed_items=sum(
            bool(item.followup and item.followup.status == "done") for item in items
        ),
        total_items=len(items),
        items=items,
    )


def read_outcomes(
    session: Session,
    classroom: Classroom,
    task: ClassroomExercise,
    offset: int,
    limit: int,
) -> FollowupOutcomes:
    """Teacher-only, item-matched evidence of a targeted-practice assignment."""
    source = _source_exercise(session, classroom, task)
    page = (task.target_students or [])[offset : offset + limit]
    student_ids = [uuid.UUID(row["student_id"]) for row in page]
    item_ids = _outcome_item_ids(task)
    before = task.published_at or task.created_at

    originals, current = _outcome_attempt_maps(
        session, classroom, task, source, student_ids, item_ids, before
    )
    locked = _locked_students(session, source, student_ids)
    rows = [
        _student_outcome(target, task, originals, current, locked) for target in page
    ]
    return FollowupOutcomes(
        task_id=task.id,
        title=task.title,
        source_title=source.title if source else None,
        assigned_at=before,
        total_students=len(task.target_students or []),
        students=rows,
    )
