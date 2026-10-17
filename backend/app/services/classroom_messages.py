"""Student help and teacher reminders with explicit read receipts."""

import uuid

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import Classroom, ClassroomMessage, Student, get_datetime_utc


def request_help(
    session: Session,
    student: Student,
    creator: uuid.UUID,
    classroom_id: uuid.UUID,
    request_id: uuid.UUID,
    category: str,
    text: str,
) -> ClassroomMessage:
    session.refresh(student, with_for_update=True)
    if student.classroom_id != classroom_id:
        raise HTTPException(403, detail="Student not in classroom")
    previous = session.exec(
        select(ClassroomMessage).where(
            ClassroomMessage.student_id == student.id,
            ClassroomMessage.kind == "help",
            ClassroomMessage.request_id == request_id,
        )
    ).first()
    if previous:
        if previous.category != category or previous.text != text.strip():
            raise HTTPException(409, detail="Class message request conflict")
        return previous
    active = session.exec(
        select(ClassroomMessage).where(
            ClassroomMessage.student_id == student.id,
            ClassroomMessage.kind == "help",
            col(ClassroomMessage.resolved_at).is_(None),
        )
    ).first()
    if active:
        raise HTTPException(409, detail="Help request already open")
    row = ClassroomMessage(
        classroom_id=student.classroom_id,
        student_id=student.id,
        created_by=creator,
        request_id=request_id,
        kind="help",
        category=category,
        text=text.strip(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def send_reminders(
    session: Session,
    classroom: Classroom,
    students: list[Student],
    creator: uuid.UUID,
    request_id: uuid.UUID,
    text: str,
) -> list[ClassroomMessage]:
    session.refresh(classroom, with_for_update=True)
    existing = list(
        session.exec(
            select(ClassroomMessage).where(
                ClassroomMessage.classroom_id == classroom.id,
                ClassroomMessage.kind == "reminder",
                ClassroomMessage.request_id == request_id,
            )
        ).all()
    )
    if existing:
        if {row.student_id for row in existing} != {
            student.id for student in students
        } or any(
            row.text != text.strip() or row.created_by != creator for row in existing
        ):
            raise HTTPException(409, detail="Class message request conflict")
        return existing
    if not students or not text.strip():
        raise HTTPException(422, detail="Invalid reminder")
    # Recheck membership under the roster lock before sending.
    for student in students:
        session.refresh(student)
        if student.classroom_id != classroom.id:
            raise HTTPException(422, detail="Invalid reminder recipients")
    rows = [
        ClassroomMessage(
            classroom_id=classroom.id,
            student_id=student.id,
            created_by=creator,
            request_id=request_id,
            kind="reminder",
            text=text.strip(),
        )
        for student in students
    ]
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def acknowledge_message(
    session: Session, row: ClassroomMessage, action: str
) -> ClassroomMessage:
    session.refresh(row, with_for_update=True)
    if action == "read":
        row.read_at = row.read_at or get_datetime_utc()
    elif row.resolved_at is None:
        row.resolved_at = get_datetime_utc()
        row.resolution = action
        if action == "resolved":
            row.read_at = row.read_at or row.resolved_at
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
