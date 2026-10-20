"""教师发布补练与学生独立练习入口。"""

import uuid
from datetime import datetime
from typing import Literal, cast

from fastapi import HTTPException, Query
from sqlalchemy import Uuid, column, func, literal
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
    _today_in_practice_tz,
    router,
)
from app.models import Attempt, ClassroomExercise, PracticeSession, Student
from app.services import followups, teaching_actions


class FollowupCreate(SQLModel):
    source_exercise_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class FollowupItem(SQLModel):
    id: uuid.UUID
    type: str
    text: str


class FollowupProgress(SQLModel):
    student_id: uuid.UUID
    display_name: str
    done_count: int
    total_count: int
    has_pending: bool
    has_failures: bool
    session_id: uuid.UUID | None


class FollowupPublic(SQLModel):
    id: uuid.UUID
    title: str
    status: Literal["followup", "followup_closed"]
    source_exercise_id: uuid.UUID | None
    created_at: datetime | None
    item_count: int
    targets: list[FollowupProgress]


class FollowupCreated(SQLModel):
    id: uuid.UUID


class FollowupStarted(SQLModel):
    session_id: uuid.UUID


def task_of(
    session: SessionDep, classroom_id: uuid.UUID, task_id: uuid.UUID
) -> ClassroomExercise:
    task = session.get(ClassroomExercise, task_id)
    if (
        task is None
        or task.classroom_id != classroom_id
        or task.status not in (followups.FOLLOWUP, followups.CANCELLED)
    ):
        raise HTTPException(404, detail="Followup not found")
    return task


@router.get(
    "/{code}/exercises/{exercise_id}/followup-items", response_model=list[FollowupItem]
)
def read_followup_items(
    session: SessionDep, code: str, exercise_id: uuid.UUID, current_user: CurrentUser
) -> list[FollowupItem]:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    source = session.get(ClassroomExercise, exercise_id)
    if (
        source is None
        or source.classroom_id != classroom.id
        or source.status not in ("published", "archived")
    ):
        raise HTTPException(404, detail="Exercise not found")
    return [
        FollowupItem(
            id=uuid.UUID(str(i["id"])), type=str(i["type"]), text=str(i.get("text", ""))
        )
        for i in source.snapshot_items
        if i.get("type") in ("passage", "repeat", "question")
    ]


@router.post("/{code}/followups", response_model=FollowupCreated)
def create_class_followup(
    session: SessionDep, code: str, body: FollowupCreate, current_user: CurrentUser
) -> FollowupCreated:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    source = session.get(ClassroomExercise, body.source_exercise_id)
    if (
        source is None
        or source.classroom_id != classroom.id
        or source.status not in ("published", "archived")
    ):
        raise HTTPException(404, detail="Exercise not found")
    students = list(
        session.exec(
            select(Student).where(
                Student.classroom_id == classroom.id,
                col(Student.id).in_(body.student_ids),
            )
        ).all()
    )
    if len(students) != len(set(body.student_ids)) or not body.title.strip():
        raise HTTPException(422, detail="Invalid followup recipients")
    task = followups.create_followup(
        session, classroom, source, students, body.item_ids, body.title, current_user.id
    )
    return FollowupCreated(id=task.id)


class IndividualFollowupTarget(SQLModel):
    student_id: uuid.UUID
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class IndividualFollowupCreate(SQLModel):
    request_id: uuid.UUID
    source_exercise_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    targets: list[IndividualFollowupTarget] = Field(min_length=1, max_length=100)


class IndividualFollowupCreated(SQLModel):
    task_ids: list[uuid.UUID]


@router.post(
    "/{code}/followups/individualized", response_model=IndividualFollowupCreated
)
def create_individual_class_followups(
    session: SessionDep,
    code: str,
    body: IndividualFollowupCreate,
    current_user: CurrentUser,
) -> IndividualFollowupCreated:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    source = session.get(ClassroomExercise, body.source_exercise_id)
    if (
        source is None
        or source.classroom_id != classroom.id
        or source.status not in ("published", "archived")
    ):
        raise HTTPException(404, detail="Exercise not found")
    targets = {target.student_id: target.item_ids for target in body.targets}
    if len(targets) != len(body.targets):
        raise HTTPException(422, detail="Invalid followup recipients")
    students = list(
        session.exec(
            select(Student).where(
                Student.classroom_id == classroom.id, col(Student.id).in_(targets)
            )
        ).all()
    )
    receipt = teaching_actions.create_individual_followups(
        session,
        classroom,
        source,
        students,
        targets,
        body.title,
        current_user.id,
        body.request_id,
    )
    return IndividualFollowupCreated(
        task_ids=[uuid.UUID(value) for value in receipt.task_ids]
    )


def _has_incomplete_target(
    classroom_id: uuid.UUID, student_id: uuid.UUID | None
) -> ColumnElement[bool]:
    """Correlate against the fixed task snapshots, never today's classroom roster.

    最新作答状态先按全班补练会话一次 DISTINCT ON 聚合，再 LEFT JOIN 回
    JSON 展开行：原实现是每个 (target,item) 对各跑一次相关 LIMIT-1 子查询，
    history 视图（任务全部完成）必须穷尽所有对，任务×学生×题的乘积会放大
    成数千次索引查找。LEFT JOIN 未命中（无作答）为 NULL，与原来「无作答
    即未完成」口径一致。
    """
    latest = (
        select(
            col(PracticeSession.assignment_id).label("assignment_id"),
            col(PracticeSession.student_id).label("student_id"),
            col(Attempt.item_id).label("item_id"),
            col(Attempt.status).label("status"),
        )
        .select_from(Attempt)
        .join(PracticeSession, col(Attempt.session_id) == col(PracticeSession.id))
        .where(
            PracticeSession.classroom_id == classroom_id,
            PracticeSession.mode == followups.FOLLOWUP,
            col(PracticeSession.assignment_id).is_not(None),
        )
        .order_by(
            col(PracticeSession.assignment_id),
            col(PracticeSession.student_id),
            col(Attempt.item_id),
            col(Attempt.created_at).desc(),
            col(Attempt.id).desc(),
        )
        .distinct(
            col(PracticeSession.assignment_id),
            col(PracticeSession.student_id),
            col(Attempt.item_id),
        )
    ).subquery("latest_followup_status")
    targets = func.jsonb_array_elements(
        func.coalesce(
            func.nullif(
                sql_cast(col(ClassroomExercise.target_students), JSONB),
                literal(JSONB.NULL, JSONB),
            ),
            literal([], JSONB),
        )
    ).table_valued(column("value", JSONB), name="target", joins_implicitly=True)
    items = func.jsonb_array_elements(
        sql_cast(col(ClassroomExercise.snapshot_items), JSONB)
    ).table_valued(column("value", JSONB), name="item", joins_implicitly=True)
    # latest 按键（任务,学生,题）DISTINCT ON 至多一行：小 EXISTS 探测即可判
    # 「最新是否 done」；无行（含完全未作答）同样算未完成，与原口径一致。
    # latest 本身与外层无关联，PG 计划为一次聚合、逐对哈希探测
    done_row = (
        select(1)
        .select_from(latest)
        .where(
            latest.c.assignment_id == col(ClassroomExercise.id),
            latest.c.student_id == sql_cast(targets.c.value["student_id"].astext, Uuid),
            latest.c.item_id == sql_cast(items.c.value["id"].astext, Uuid),
            latest.c.status == "done",
        )
        .correlate(ClassroomExercise, targets, items)
    )
    incomplete = (
        select(1)
        .select_from(targets, items)
        .where(
            items.c.value["type"].astext.is_distinct_from("instruction"),
            # An older success must not hide the latest failed or pending retry.
            ~done_row.exists(),
        )
        .correlate(ClassroomExercise)
    )
    if student_id is not None:
        incomplete = incomplete.where(
            targets.c.value["student_id"].astext == str(student_id)
        )
    return incomplete.exists()


@router.get("/{code}/followups", response_model=list[FollowupPublic])
def list_class_followups(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    status: Literal["active", "history", "all"] = "all",
    offset: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[FollowupPublic]:
    """Page tasks by the caller's unfinished work or history, newest first."""
    classroom = _get_classroom(session, code)
    own_student = (
        _student_profile_of(session, classroom, current_user)
        if current_user.role == "student"
        else None
    )
    if own_student is None:
        _require_classroom_teacher(classroom, current_user)
    statement = select(ClassroomExercise).where(
        ClassroomExercise.classroom_id == classroom.id,
        col(ClassroomExercise.status).in_([followups.FOLLOWUP, followups.CANCELLED]),
    )
    if own_student is not None:
        statement = statement.where(
            sql_cast(col(ClassroomExercise.target_students), JSONB).contains(
                [{"student_id": str(own_student.id)}]
            )
        )
    if status != "all":
        active = (col(ClassroomExercise.status) == followups.FOLLOWUP) & (
            _has_incomplete_target(
                classroom.id, own_student.id if own_student else None
            )
        )
        statement = statement.where(active if status == "active" else ~active)
    # Both recipient and completion filtering must precede LIMIT/OFFSET.
    tasks = session.exec(
        statement.order_by(
            col(ClassroomExercise.created_at).desc(), col(ClassroomExercise.id).desc()
        )
        .offset(offset)
        .limit(limit)
    ).all()
    task_ids = [t.id for t in tasks]
    sessions = (
        session.exec(
            select(PracticeSession).where(
                col(PracticeSession.assignment_id).in_(task_ids),
                PracticeSession.mode == followups.FOLLOWUP,
                PracticeSession.student_id == own_student.id
                if own_student is not None
                else True,
            )
        ).all()
        if task_ids
        else []
    )
    by_target = {(ps.assignment_id, str(ps.student_id)): ps for ps in sessions}
    attempts = (
        session.exec(
            select(Attempt.session_id, Attempt.item_id, Attempt.status)
            .where(col(Attempt.session_id).in_([ps.id for ps in sessions]))
            .distinct(col(Attempt.session_id), col(Attempt.item_id))
            .order_by(
                col(Attempt.session_id),
                col(Attempt.item_id),
                col(Attempt.created_at).desc(),
                col(Attempt.id).desc(),
            )
        ).all()
        if sessions
        else []
    )
    latest = {(sid, iid): attempt_status for sid, iid, attempt_status in attempts}
    result = []
    for task in tasks:
        ids = {
            uuid.UUID(str(i["id"]))
            for i in task.snapshot_items
            if i.get("type") != "instruction"
        }
        rows = []
        for target in task.target_students or []:
            if own_student is not None and target["student_id"] != str(own_student.id):
                continue
            ps = by_target.get((task.id, target["student_id"]))
            statuses = [
                latest.get((ps.id, iid), "missing") if ps else "missing" for iid in ids
            ]
            rows.append(
                FollowupProgress(
                    student_id=uuid.UUID(target["student_id"]),
                    display_name=target["display_name"],
                    done_count=statuses.count("done"),
                    total_count=len(ids),
                    has_pending=any(s in ("queued", "scoring") for s in statuses),
                    has_failures="failed" in statuses,
                    session_id=ps.id if ps else None,
                )
            )
        result.append(
            FollowupPublic(
                id=task.id,
                title=task.title,
                status=cast(Literal["followup", "followup_closed"], task.status),
                source_exercise_id=task.source_exercise_id,
                created_at=task.created_at,
                item_count=len(ids),
                targets=rows,
            )
        )
    return result


@router.post("/{code}/followups/{task_id}/start", response_model=FollowupStarted)
def start_class_followup(
    session: SessionDep, code: str, task_id: uuid.UUID, current_user: StudentUserDep
) -> FollowupStarted:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    task = task_of(session, classroom.id, task_id)
    session.refresh(task, with_for_update=True)
    followups.require_followup_student(task, student)
    from app.crud import get_or_create_followup_session

    ps = get_or_create_followup_session(session, task, student, _today_in_practice_tz())
    return FollowupStarted(session_id=ps.id)


@router.post("/{code}/followups/{task_id}/cancel", response_model=None)
def cancel_class_followup(
    session: SessionDep, code: str, task_id: uuid.UUID, current_user: CurrentUser
) -> None:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    task = task_of(session, classroom.id, task_id)
    session.refresh(task, with_for_update=True)
    task.status = followups.CANCELLED
    session.add(task)
    session.commit()
