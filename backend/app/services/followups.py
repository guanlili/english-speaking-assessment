"""指定学生补练：固定名单和发布快照，原课堂与考试保持独立。"""

import uuid
from copy import deepcopy

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    Classroom,
    ClassroomExercise,
    PracticeSession,
    Student,
    get_datetime_utc,
)
from app.services import exam
from app.services.exercise import next_exercise_version

FOLLOWUP = "followup"
CANCELLED = "followup_closed"


def require_followup_student(
    task: ClassroomExercise, student: Student, *, writable: bool = True
) -> None:
    if task.status not in (FOLLOWUP, CANCELLED) or not any(
        t.get("student_id") == str(student.id) for t in task.target_students or []
    ):
        raise HTTPException(404, detail="Followup not found")
    if writable and task.status == CANCELLED:
        raise HTTPException(422, detail="Followup cancelled")


def check_session_open(session: Session, ps: PracticeSession, student: Student) -> None:
    if ps.mode != FOLLOWUP:
        return
    task = session.get(ClassroomExercise, ps.assignment_id)
    if task is None:
        raise HTTPException(404, detail="Followup not found")
    require_followup_student(task, student)


def create_followup(
    session: Session,
    classroom: Classroom,
    source: ClassroomExercise,
    students: list[Student],
    item_ids: list[uuid.UUID],
    title: str,
    creator: uuid.UUID,
    *,
    commit: bool = True,
) -> ClassroomExercise:
    session.refresh(classroom, with_for_update=True)
    for student in students:
        session.refresh(student)
        if student.classroom_id != classroom.id:
            raise HTTPException(422, detail="Invalid followup recipients")
    allowed = {
        str(i["id"])
        for i in source.snapshot_items
        if i.get("type") in ("passage", "repeat", "question")
    }
    selected = {str(i) for i in item_ids}
    if not selected or not selected <= allowed:
        raise HTTPException(422, detail="Invalid followup items")
    if source.is_exam:
        if classroom.current_exercise_id == source.id:
            raise HTTPException(
                422, detail="Active exam cannot be assigned as followup"
            )
        exam_sessions = session.exec(
            select(PracticeSession).where(
                PracticeSession.assignment_id == source.id,
                col(PracticeSession.student_id).in_([s.id for s in students]),
            )
        ).all()
        # 旧式（无 exam_flow）考试的遮罩判定需要首答时间：一次预取，不逐会话查询
        first = exam.first_submitted_by_session(
            session, [ps.id for ps in exam_sessions]
        )
        for ps in exam_sessions:
            if ps.exam_started_at and exam.exam_feedback_locked(
                session, ps, source, first_submitted=first.get(ps.id, {})
            ):
                raise HTTPException(422, detail="Student exam still in progress")
    snapshots = [
        deepcopy(i) for i in source.snapshot_items if str(i.get("id")) in selected
    ]
    for item in snapshots:
        item.pop("exam_flow", None)
    task = ClassroomExercise(
        classroom_id=classroom.id,
        version_no=next_exercise_version(session, classroom.id),
        title=title.strip(),
        status=FOLLOWUP,
        snapshot_items=snapshots,
        created_by=creator,
        published_at=get_datetime_utc(),
        source_exercise_id=source.id,
        target_students=[
            {"student_id": str(s.id), "display_name": s.display_name} for s in students
        ],
        is_exam=False,
    )
    session.add(task)
    session.flush()
    if commit:
        session.commit()
    session.refresh(task)
    return task
