import random
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

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


def get_user_by_username(*, session: Session, username: str) -> User | None:
    return session.exec(
        select(User).where(User.username == username)  # type: ignore[arg-type]
    ).first()


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, account: str, password: str) -> User | None:
    """统一登录：account 为学号（学生）或邮箱（教师/管理员）。"""
    db_user = get_user_by_username(session=session, username=account)
    if db_user is None:
        db_user = get_user_by_email(session=session, email=account)
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


def slugify_title(title: str) -> str:
    """标题 → slug；无 ASCII 词元（纯中文）时用随机码兜底。"""
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return base[:90].strip("-") or f"p-{uuid.uuid4().hex[:8]}"


def unique_passage_slug(session: Session, base: str) -> str:
    """slug 撞名时追加 -2/-3…（上限后换随机后缀，避免死循环）。"""
    slug = base
    for i in range(2, 500):
        if session.exec(select(Passage).where(Passage.slug == slug)).first() is None:
            return slug
        suffix = f"-{i}"
        slug = f"{base[: 100 - len(suffix)]}{suffix}"
    return f"{base[:90]}-{uuid.uuid4().hex[:8]}"


def create_passage(*, session: Session, passage_in: PassageCreate) -> Passage:
    # slug 未填时自动生成（管理端/脚本共用同一套规则）
    slug = passage_in.slug or unique_passage_slug(
        session, slugify_title(passage_in.title)
    )
    payload = passage_in.model_dump(exclude={"slug"}) | {"slug": slug}
    db_passage = Passage.model_validate(payload)
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
    *, session: Session, classroom: Classroom, user: User, display_name: str | None
) -> Student:
    """账号制入班：一个账号一间课堂一份学生档案（幂等，重复入班返回已有档案）。

    并发用 IntegrityError 重试（user/classroom 唯一索引与显示名唯一约束）。
    """
    existing = session.exec(
        select(Student).where(
            Student.classroom_id == classroom.id,  # type: ignore[arg-type]
            Student.user_id == user.id,  # type: ignore[arg-type]
        )
    ).first()
    if existing is not None:
        return existing
    name = (
        (display_name or "").strip()
        or (user.full_name or "").strip()
        or user.username
        or "同学"
    )
    for _attempt in range(10):
        duplicate = session.exec(
            select(Student).where(
                Student.classroom_id == classroom.id,  # type: ignore[arg-type]
                Student.display_name == name,
            )
        ).first()
        suffix = None if duplicate is None else f"{random.randint(1000, 9999)}"  # noqa: S311
        student = Student(
            classroom_id=classroom.id,
            user_id=user.id,
            display_name=name[:64],
            suffix=suffix,
        )
        session.add(student)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            # 并发同账号入班：重查直接返回
            existing = session.exec(
                select(Student).where(
                    Student.classroom_id == classroom.id,  # type: ignore[arg-type]
                    Student.user_id == user.id,  # type: ignore[arg-type]
                )
            ).first()
            if existing is not None:
                return existing
            continue
        session.refresh(student)
        return student
    raise RuntimeError("生成唯一学生显示名失败（重试耗尽）")


def get_student(*, session: Session, student_id: uuid.UUID) -> Student | None:
    return session.get(Student, student_id)


def get_or_create_today_session(
    *,
    session: Session,
    classroom: Classroom,
    student: Student,
    today: date,
    passage_id: uuid.UUID | None = None,
    mode: str = "daily",
    assignment_id: uuid.UUID | None = None,
) -> PracticeSession:
    """取当日会话；explore 按篇目各一轮；daily 按篇目复用。

    daily 以（学生、日期、篇目、发布快照）为复用键：老师中途切换指派
    即使锚点篇目不变，也会自动开新轮，旧轮作答与星级保留。
    """
    statement = select(PracticeSession).where(
        PracticeSession.student_id == student.id,
        PracticeSession.session_date == today,
    )
    if mode == "explore":
        statement = statement.where(
            PracticeSession.passage_id == passage_id,
            PracticeSession.mode == "explore",
        )
    else:
        statement = statement.where(PracticeSession.mode == "daily")
        if passage_id is None:
            statement = statement.where(col(PracticeSession.passage_id).is_(None))
        else:
            statement = statement.where(PracticeSession.passage_id == passage_id)
        if assignment_id is None:
            statement = statement.where(col(PracticeSession.assignment_id).is_(None))
        else:
            statement = statement.where(PracticeSession.assignment_id == assignment_id)
    existing = session.exec(statement).first()
    if existing is not None:
        return existing
    practice_session = PracticeSession(
        classroom_id=classroom.id,
        student_id=student.id,
        band=student.current_band,
        passage_id=passage_id,
        mode=mode,
        assignment_id=assignment_id,
        session_date=today,
    )
    session.add(practice_session)
    try:
        session.commit()
    except IntegrityError:
        # 并发创建：另一请求已插入同键会话，回滚后重新查询
        session.rollback()
        existing = session.exec(statement).first()
        if existing is not None:
            return existing
        raise
    session.refresh(practice_session)
    return practice_session


def create_attempt(*, session: Session, attempt_in: Attempt) -> Attempt:
    session.add(attempt_in)
    session.commit()
    session.refresh(attempt_in)
    return attempt_in
