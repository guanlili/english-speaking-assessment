"""Class-scoped help, reminders, and student-controlled read receipts."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, Query
from sqlalchemy import case
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
    router,
)
from app.models import ClassroomMessage, Student
from app.services import classroom_messages


class ClassMessagePublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    display_name: str
    kind: str
    category: str | None
    text: str
    created_at: datetime
    read_at: datetime | None
    resolved_at: datetime | None
    resolution: str | None


class HelpRequestWrite(SQLModel):
    request_id: uuid.UUID
    category: Literal["operation", "audio", "understanding", "other"]
    text: str = Field(default="", max_length=500)


class ReminderWrite(SQLModel):
    request_id: uuid.UUID
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=500)


def public_message(row: ClassroomMessage, student: Student) -> ClassMessagePublic:
    return ClassMessagePublic(
        **row.model_dump(),
        display_name=student.display_name
        + (f"·{student.suffix}" if student.suffix else ""),
    )


@router.post("/{code}/help-requests", response_model=ClassMessagePublic)
def create_help_request(
    session: SessionDep, code: str, body: HelpRequestWrite, current_user: StudentUserDep
) -> ClassMessagePublic:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return public_message(
        classroom_messages.request_help(
            session,
            student,
            current_user.id,
            classroom.id,
            body.request_id,
            body.category,
            body.text,
        ),
        student,
    )


@router.get("/{code}/my-messages", response_model=list[ClassMessagePublic])
def read_my_class_messages(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ClassMessagePublic]:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    rows = session.exec(
        select(ClassroomMessage)
        .where(
            ClassroomMessage.classroom_id == classroom.id,
            ClassroomMessage.student_id == student.id,
        )
        .order_by(
            case(
                (
                    (col(ClassroomMessage.kind) == "help")
                    & col(ClassroomMessage.resolved_at).is_(None),
                    0,
                ),
                (
                    (col(ClassroomMessage.kind) == "reminder")
                    & col(ClassroomMessage.read_at).is_(None),
                    1,
                ),
                else_=2,
            ),
            col(ClassroomMessage.created_at).desc(),
            col(ClassroomMessage.id).desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return [public_message(row, student) for row in rows]


@router.get("/{code}/class-messages", response_model=list[ClassMessagePublic])
def read_teacher_class_messages(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    kind: Literal["help", "reminder"],
    status: Literal["open", "all"] = "all",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ClassMessagePublic]:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    statement = (
        select(ClassroomMessage, Student)
        .join(Student, col(ClassroomMessage.student_id) == col(Student.id))
        .where(
            ClassroomMessage.classroom_id == classroom.id,
            Student.classroom_id == classroom.id,
            ClassroomMessage.kind == kind,
        )
    )
    if status == "open":
        statement = statement.where(
            col(ClassroomMessage.resolved_at).is_(None)
            if kind == "help"
            else col(ClassroomMessage.read_at).is_(None)
        )
    rows = session.exec(
        statement.order_by(
            col(ClassroomMessage.created_at).desc(), col(ClassroomMessage.id).desc()
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return [public_message(row, student) for row, student in rows]


@router.post("/{code}/reminders", response_model=list[ClassMessagePublic])
def create_class_reminders(
    session: SessionDep, code: str, body: ReminderWrite, current_user: CurrentUser
) -> list[ClassMessagePublic]:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    students = list(
        session.exec(
            select(Student).where(
                Student.classroom_id == classroom.id,
                col(Student.id).in_(body.student_ids),
            )
        ).all()
    )
    if len(students) != len(set(body.student_ids)):
        raise HTTPException(422, detail="Invalid reminder recipients")
    rows = classroom_messages.send_reminders(
        session, classroom, students, current_user.id, body.request_id, body.text
    )
    by_id = {student.id: student for student in students}
    return [public_message(row, by_id[row.student_id]) for row in rows]


@router.post(
    "/{code}/class-messages/{message_id}/{action}", response_model=ClassMessagePublic
)
def act_on_class_message(
    session: SessionDep,
    code: str,
    message_id: uuid.UUID,
    action: Literal["read", "resolved", "withdrawn"],
    current_user: CurrentUser,
) -> ClassMessagePublic:
    classroom = _get_classroom(session, code)
    row = session.get(ClassroomMessage, message_id)
    if row is None or row.classroom_id != classroom.id:
        raise HTTPException(404, detail="Class message not found")
    student = session.get(Student, row.student_id)
    if student is None or student.classroom_id != classroom.id:
        raise HTTPException(404, detail="Class message not found")
    if current_user.role == "student" and not current_user.is_superuser:
        own = _student_profile_of(session, classroom, current_user)
        if own.id != row.student_id:
            raise HTTPException(404, detail="Class message not found")
        if not (
            (action == "read" and row.kind == "reminder")
            or (action == "withdrawn" and row.kind == "help")
        ):
            raise HTTPException(403, detail="Class message action forbidden")
    else:
        _require_classroom_teacher(classroom, current_user)
        if row.kind != "help" or action == "withdrawn":
            raise HTTPException(403, detail="Class message action forbidden")
    return public_message(
        classroom_messages.acknowledge_message(session, row, action), student
    )
