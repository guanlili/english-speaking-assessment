import logging
import random
import re
import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    Passage,
    PassageCreate,
    PracticeSession,
    Student,
    Unit,
    User,
    UserCreate,
    UserUpdate,
)

logger = logging.getLogger(__name__)


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


def derive_passage_topic(
    session: Session, unit_id: uuid.UUID | None, topic: str
) -> str:
    """篇目主题单一事实源：挂单元时以单元主题为准，未挂单元才用传入值。"""
    if unit_id is not None:
        unit = session.get(Unit, unit_id)
        if unit is not None:
            return unit.topic
    return topic


def create_passage(*, session: Session, passage_in: PassageCreate) -> Passage:
    # slug 未填时自动生成（管理端/脚本共用同一套规则）
    slug = passage_in.slug or unique_passage_slug(
        session, slugify_title(passage_in.title)
    )
    payload = passage_in.model_dump(exclude={"slug"}) | {"slug": slug}
    # 挂单元的篇目主题跟随单元（题库三层：主题→篇目→句子）
    payload["topic"] = derive_passage_topic(
        session, passage_in.unit_id, passage_in.topic
    )
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


def classroom_teacher_allowed(classroom: Classroom, user: User) -> bool:
    """教师越权判定唯一事实源（纯函数，不抛错）：

    本班 owner（绑定教师）或管理员可过；owner 未绑定的课堂任何教师都
    不可过（课堂码不是教师凭据）。students / class_shared 两套适配层
    停用课堂与 403 文案语义不同，但判定核心必须是同一个。"""
    if user.is_superuser:
        return True
    return classroom.owner_id is not None and classroom.owner_id == user.id


def ensure_class_size_feasible(
    *, session: Session, classroom: Classroom, new_size: int
) -> None:
    """调整班容前置校验：新上限不得低于班内现有档案数。

    口径与 join_classroom 的容量检查一致（班内全部档案，含被移出后的
    孤儿档案——它们仍在花名册上）。不满足抛 422（稳定 detail）。"""
    enrolled_count = session.exec(
        select(func.count())
        .select_from(Student)
        .where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
    ).one()
    if new_size < enrolled_count:
        raise HTTPException(
            status_code=422,
            detail=f"班级人数上限不能低于当前已有档案数（{enrolled_count} 人）",
        )


class ClassroomFullError(Exception):
    """入班被拒：班内学生档案数已达课堂容量上限（class_size）。"""


def join_classroom(
    *, session: Session, classroom: Classroom, user: User, display_name: str | None
) -> Student:
    """账号制入班：一个账号一间课堂一份学生档案（幂等，重复入班返回已有档案）。

    多班归属：同一账号可加入多间课堂，各班档案独立。
    并发用 IntegrityError 重试（user/classroom 唯一索引与显示名唯一约束）；
    班内档案数达到 class_size 时抛 ClassroomFullError（路由转 409）。
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
        # 容量检查-插入之间无原子性：并发抢最后一个名额会双双通过检查超员。
        # 对课堂行 FOR UPDATE 串行化同班并发入班（毫秒级临界区，提交即释放；
        # 教师批量导入期间锁持有到导入事务结束，自加入学生会排队等导入完成）
        locked_classroom = session.exec(
            select(Classroom).where(Classroom.id == classroom.id).with_for_update()
        ).first()
        if locked_classroom is None:
            raise HTTPException(status_code=404, detail="Classroom not found")
        duplicate = session.exec(
            select(Student).where(
                Student.classroom_id == classroom.id,  # type: ignore[arg-type]
                Student.display_name == name,
            )
        ).first()
        # 容量按班内档案数（含被移出后的孤儿档案，仍在花名册上）计算
        enrolled_count = session.exec(
            select(func.count())
            .select_from(Student)
            .where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
        ).one()
        if enrolled_count >= locked_classroom.class_size:
            raise ClassroomFullError()
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
        except IntegrityError as exc:
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
            # 重查无既有档案：多半是随机后缀显示名撞车，静默重试会让
            # 排查「为何没入班」失去线索——留一条再继续
            logger.warning(
                "join_classroom integrity conflict without existing profile, "
                "retrying user=%s classroom=%s: %s",
                user.id,
                classroom.id,
                exc,
            )
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
    """取当日会话；explore 按篇目各一轮；daily 按发布快照或自主练习各一轮。

    唯一键：
    - assignment_id IS NOT NULL → (student, date, mode, assignment_id)
    - mode='daily' 且 assignment_id IS NULL → 每日一条自主轮
    - mode='explore' → (student, date, mode, passage_id)
    """
    if assignment_id is not None and mode == "daily":
        # 考试不允许隔天重考：计时/每题一次/阶段机全部挂在会话行上，而会话
        # 按天建轮——该生已开考过这场发布时必须回到那一场（已结束则直出
        # 结果态），否则考完次日再点入口会整场重考、每题再得作答权。守卫
        # 放在当日查询之前，兼容线上已存在的「隔天空会话 + 已开考前轮」。
        # 要让全班重考请重新发布（每次发布都是新的 assignment）。
        exercise = session.get(ClassroomExercise, assignment_id)
        if exercise is not None and exercise.is_exam:
            prior = session.exec(
                select(PracticeSession)
                .where(
                    PracticeSession.student_id == student.id,
                    PracticeSession.assignment_id == assignment_id,
                    col(PracticeSession.exam_started_at).is_not(None),
                )
                .order_by(col(PracticeSession.created_at).desc())
            ).first()
            if prior is not None:
                return prior
    statement = select(PracticeSession).where(
        PracticeSession.student_id == student.id,
        PracticeSession.session_date == today,
        PracticeSession.mode == mode,
    )
    if mode == "explore":
        statement = statement.where(PracticeSession.passage_id == passage_id)
    elif assignment_id is not None:
        statement = statement.where(PracticeSession.assignment_id == assignment_id)
    else:
        statement = statement.where(col(PracticeSession.assignment_id).is_(None))
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
