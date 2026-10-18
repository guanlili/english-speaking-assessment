"""Student help and teacher reminders with explicit read receipts."""

import uuid
from datetime import datetime, timedelta

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
    due_at: datetime | None = None,
    reminder_of: uuid.UUID | None = None,
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
            row.text != text.strip()
            or row.created_by != creator
            or row.due_at != due_at
            or row.reminder_of != reminder_of
            for row in existing
        ):
            raise HTTPException(409, detail="Class message request conflict")
        return existing
    if due_at is not None and reminder_of is None and due_at <= get_datetime_utc():
        raise HTTPException(422, detail="Reminder deadline must be in future")
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
            due_at=due_at,
            reminder_of=reminder_of,
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
    if action == "read" and row.kind == "reminder":
        classroom = session.get(Classroom, row.classroom_id)
        if classroom:
            session.refresh(classroom, with_for_update=True)
    session.refresh(row, with_for_update=True)
    if action == "read":
        if row.kind == "reminder":
            # Serialize against repeats and acknowledge the same reminder chain.
            root = row.reminder_of or row.id
            for related in session.exec(
                select(ClassroomMessage)
                .where(
                    ClassroomMessage.classroom_id == row.classroom_id,
                    ClassroomMessage.student_id == row.student_id,
                    (col(ClassroomMessage.id) == root)
                    | (col(ClassroomMessage.reminder_of) == root),
                )
                .with_for_update()
            ).all():
                related.read_at = related.read_at or get_datetime_utc()
                session.add(related)
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


def reply_to_help(
    session: Session, row: ClassroomMessage, text: str, revision: int, resolve: bool
) -> ClassroomMessage:
    session.refresh(row, with_for_update=True)
    if row.kind != "help" or row.resolution == "withdrawn":
        raise HTTPException(422, detail="Help request unavailable")
    if row.reply_revision != revision:
        raise HTTPException(409, detail="Help reply revision conflict")
    if not text.strip():
        raise HTTPException(422, detail="Empty help reply")
    row.reply_text = text.strip()
    row.replied_at = get_datetime_utc()
    row.reply_revision += 1
    row.read_at = row.read_at or row.replied_at
    if resolve and row.resolved_at is None:
        row.resolved_at = row.replied_at
        row.resolution = "resolved"
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def repeat_reminder(
    session: Session,
    classroom: Classroom,
    row: ClassroomMessage,
    student: Student,
    creator: uuid.UUID,
    request_id: uuid.UUID,
) -> ClassroomMessage:
    session.refresh(classroom, with_for_update=True)
    session.refresh(row, with_for_update=True)
    if row.kind != "reminder":
        raise HTTPException(422, detail="Invalid reminder")
    root = row.reminder_of or row.id
    previous = session.exec(
        select(ClassroomMessage).where(
            ClassroomMessage.classroom_id == classroom.id,
            ClassroomMessage.kind == "reminder",
            ClassroomMessage.request_id == request_id,
        )
    ).first()
    if previous:
        if (
            previous.reminder_of != root
            or previous.student_id != student.id
            or previous.created_by != creator
        ):
            raise HTTPException(409, detail="Class message request conflict")
        return previous
    chain = list(
        session.exec(
            select(ClassroomMessage)
            .where(
                (col(ClassroomMessage.id) == root)
                | (col(ClassroomMessage.reminder_of) == root)
            )
            .with_for_update()
        ).all()
    )
    if any(message.read_at is not None for message in chain):
        raise HTTPException(409, detail="Reminder already acknowledged")
    if any(
        message.created_at > get_datetime_utc() - timedelta(seconds=60)
        for message in chain
    ):
        raise HTTPException(429, detail="Reminder repeated too soon")
    return send_reminders(
        session, classroom, [student], creator, request_id, row.text, row.due_at, root
    )[0]
