import random
import uuid
from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    Attempt,
    Classroom,
    Passage,
    PassageCreate,
    PracticeSession,
    Student,
    User,
    UserCreate,
    UserUpdate,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_passage(*, session: Session, passage_in: PassageCreate) -> Passage:
    db_passage = Passage.model_validate(passage_in)
    session.add(db_passage)
    session.commit()
    session.refresh(db_passage)
    return db_passage


def get_attempt(*, session: Session, attempt_id: uuid.UUID) -> Attempt | None:
    return session.get(Attempt, attempt_id)


# ── 课堂 / 学生 / 会话 ────────────────────────────────────────────────


def create_classroom(*, session: Session, classroom: Classroom) -> Classroom:
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return classroom


def get_classroom_by_code(*, session: Session, code: str) -> Classroom | None:
    return session.exec(select(Classroom).where(Classroom.code == code)).first()


def join_classroom(
    *, session: Session, classroom: Classroom, display_name: str
) -> Student:
    """同名允许进入，追加 4 位区分码并返回给学生（PRD US-04）。"""
    duplicate = session.exec(
        select(Student).where(
            Student.classroom_id == classroom.id,
            Student.display_name == display_name,
        )
    ).first()
    suffix = None
    if duplicate is not None:
        suffix = f"{random.randint(1000, 9999)}"  # noqa: S311 - 展示用途区分码
    student = Student(
        classroom_id=classroom.id,
        display_name=display_name,
        suffix=suffix,
    )
    session.add(student)
    session.commit()
    session.refresh(student)
    return student


def get_student(*, session: Session, student_id: uuid.UUID) -> Student | None:
    return session.get(Student, student_id)


def get_or_create_today_session(
    *, session: Session, classroom: Classroom, student: Student, today: date
) -> PracticeSession:
    existing = session.exec(
        select(PracticeSession).where(
            PracticeSession.student_id == student.id,
            PracticeSession.session_date == today,
        )
    ).first()
    if existing is not None:
        return existing
    practice_session = PracticeSession(
        classroom_id=classroom.id,
        student_id=student.id,
        band=student.current_band,
        session_date=today,
    )
    session.add(practice_session)
    session.commit()
    session.refresh(practice_session)
    return practice_session


def create_attempt(*, session: Session, attempt_in: Attempt) -> Attempt:
    session.add(attempt_in)
    session.commit()
    session.refresh(attempt_in)
    return attempt_in
