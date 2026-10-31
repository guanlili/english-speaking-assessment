"""学生账号管理：批量导入（学号+姓名→初始密码）、名单、重置密码、移出课堂。

权限：管理员任意课堂；教师仅自己名下课堂。
导入时按「课堂+姓名」自动匹配历史匿名学生档案，把 XP/作答历史绑到新账号。
多班归属（2026-10）：学号已存在（他班已导入）且姓名一致 → 该账号加入本班，
不新建账号、不重置密码；姓名不一致仍阻断；已在本班则幂等成功。
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, col, select

from app import crud
from app.api.deps import SessionDep, StudentUserDep, TeacherUserDep
from app.core.security import DEFAULT_STUDENT_PASSWORD, get_password_hash
from app.crud import ClassroomFullError
from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    Student,
    StudentPublic,
    User,
    VocabularyAnswer,
    VocabularySession,
)

router = APIRouter(prefix="/students", tags=["students"])

logger = logging.getLogger(__name__)


def _get_classroom_in_scope(
    session: Session, current_user: User, classroom_id: uuid.UUID
) -> Classroom:
    classroom = session.get(Classroom, classroom_id)
    if classroom is None or not classroom.is_active:
        raise HTTPException(status_code=404, detail="Classroom not found")
    if not crud.classroom_teacher_allowed(classroom, current_user):
        raise HTTPException(status_code=403, detail="没有权限：只能管理自己课堂的学生")
    return classroom


def _ensure_account_reset_allowed(
    session: Session, current_user: User, user: User, *, classroom_id: uuid.UUID
) -> None:
    """重置的是账号级唯一凭证：目标必须是普通学生账号，且操作者对该账号
    名下所有班级档案都有权限——否则 B 班教师可重置共享学生/被拉进班的
    管理员，用公开默认密码冒充其在其他班级作答（账号接管面）。

    B3 起角色单源（is_superuser 已移除）：目标角色只认 role=="student"，
    校级管理员恒可重置；旧「role=student 与超管标志并存」的盲写风险不复存在。
    """
    if user.role != "student":
        raise HTTPException(status_code=403, detail="没有权限：只能重置学生账号的密码")
    if current_user.role == "admin":
        return
    # join 走 Student.classroom_id 外键推断，不写 onclause（ty 会把列 == 判成 bool）
    other_owners = session.exec(
        select(Classroom.owner_id)
        .join(Student)
        .where(
            Student.user_id == user.id,
            Student.classroom_id != classroom_id,
        )
    ).all()
    if any(owner_id != current_user.id for owner_id in other_owners):
        raise HTTPException(
            status_code=403,
            detail="没有权限：该学生账号同时属于其他教师的班级，请联系管理员重置",
        )


class StudentImportLine(SQLModel):
    username: str = Field(max_length=64)
    full_name: str = Field(max_length=255)


class StudentImportRequest(SQLModel):
    classroom_id: uuid.UUID
    lines: list[StudentImportLine]

    @field_validator("lines")
    @classmethod
    def _cap_lines(cls, v: list[StudentImportLine]) -> list[StudentImportLine]:
        # 上限防超大名单把单事务撑爆（每行还有哈希+插入）；正常班额远低于此
        if len(v) > 500:
            raise ValueError("单次最多导入 500 名学生，请分批导入")
        return v


class StudentImportRow(SQLModel):
    """导入结果行：初始密码只在本次响应返回一次，不入日志。"""

    username: str
    full_name: str
    initial_password: str | None = None
    student_id: uuid.UUID | None = None
    # 命中的历史匿名档案：XP/作答历史绑定到该账号
    merged_existing: bool = False
    # 行结果：created=新建账号 / merged=绑定历史匿名档案 / joined=已有账号加入本班
    # / already=已在班内；出错行为 None
    status: str | None = None
    error: str | None = None


class StudentImportResult(SQLModel):
    created: int
    merged: int
    # 多班归属：joined=学号已存在（他班导入过）加入本班；already=已在本班
    joined: int = 0
    already_enrolled: int = 0
    skipped: int
    rows: list[StudentImportRow]


class StudentAccountOut(SQLModel):
    student: StudentPublic
    username: str | None = None
    full_name: str | None = None
    must_change_password: bool = False


class StudentUpdate(SQLModel):
    """改班内显示名（档案级，不触碰账号与他班同名档案）。"""

    display_name: str = Field(min_length=1, max_length=64)


@router.patch("/{student_id}", response_model=StudentPublic)
def update_student(
    session: SessionDep,
    current_user: TeacherUserDep,
    student_id: uuid.UUID,
    body: StudentUpdate,
) -> Any:
    """修改学生在本班的显示名。

    档案级改名：账号信息与他班同名档案不受影响；改名后清除重名后缀
    （教师显式指定的新名）。与本班现有姓名（含无后缀同名）冲突时 422。
    """
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _get_classroom_in_scope(session, current_user, student.classroom_id)
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="姓名不能为空")
    if name != student.display_name:
        student.display_name = name[:64]
        student.suffix = None
        try:
            session.add(student)
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=422, detail="该姓名在本班已被使用，请换一个名字"
            ) from None
    session.refresh(student)
    return student


def _student_has_history(session: Session, student_id: uuid.UUID) -> bool:
    """该生在本班是否有作答记录（口语或词汇）。"""
    has_attempts = (
        session.exec(
            select(Attempt.id).where(Attempt.student_id == student_id).limit(1)  # type: ignore[arg-type]
        ).first()
        is not None
    )
    if has_attempts:
        return True
    return (
        session.exec(
            select(VocabularyAnswer.id)
            .join(
                VocabularySession,
                col(VocabularyAnswer.session_id) == col(VocabularySession.id),
            )
            .where(VocabularySession.student_id == student_id)  # type: ignore[arg-type]
            .limit(1)
        ).first()
        is not None
    )


@router.delete("/{student_id}")
def remove_student(
    session: SessionDep,
    current_user: TeacherUserDep,
    student_id: uuid.UUID,
    purge: bool = Query(default=False),
    delete_history: bool = Query(default=False),
) -> dict[str, str]:
    """把学生移出课堂（purge=false）或从名单删除档案（purge=true）。

    - 移出（默认）：仅解除账号绑定，档案与作答历史保留（重新导入相同学号
      可找回），档案仍占班级容量；
    - 删除档案（purge=true）：物理删除档案行并释放容量，其在本班的全部
      练习记录、成绩与游戏化数据按外键级联删除。有作答历史时必须
      delete_history=true 显式确认（默认 409 阻断）。
    """
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _get_classroom_in_scope(session, current_user, student.classroom_id)
    if not purge:
        student.user_id = None
        session.add(student)
        session.commit()
        return {"message": "已移出课堂（档案与历史保留，重新导入可找回）"}
    if not delete_history and _student_has_history(session, student.id):
        raise HTTPException(
            status_code=409,
            detail="该学生在本班有作答记录，删除档案将一并清除其全部练习与成绩；确认清除请重试并携带删除历史确认",
        )
    session.delete(student)
    session.commit()
    return {"message": "已从名单删除（容量已释放）"}


def _normalized_name(name: str | None) -> str:
    """姓名比对口径：去首尾空白 + casefold（大小写不敏感，兼容拼音姓名）。"""
    return (name or "").strip().casefold()


@router.post("/import", response_model=StudentImportResult)
def import_students(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: StudentImportRequest,
) -> Any:
    """批量导入学生：每行「学号 姓名」。

    - 新学号：建账号（默认密码）+ 建档案；同名历史匿名档案自动绑定（保留 XP/作答）
    - 已存在学号（他班已导入）且姓名一致：该账号加入本班，不重置密码、不另建账号
    - 已存在学号但姓名不一致（或非学生账号）：阻断该行
    - 已在本班：幂等成功（不重复建档案）
    - 班内档案数达到课堂容量（class_size）后，需要新建档案的行报错
    """
    classroom = _get_classroom_in_scope(session, current_user, body.classroom_id)
    result = StudentImportResult(
        created=0, merged=0, joined=0, already_enrolled=0, skipped=0, rows=[]
    )

    # 批量预取，替代逐行点查（50 人名单原来要 ~100 次查询）；
    # 密码哈希昂贵（argon2 数十毫秒/次），同一默认密码只哈希一次
    hashed_default_password = get_password_hash(DEFAULT_STUDENT_PASSWORD)
    wanted_usernames = {line.username.strip() for line in body.lines}
    # 多租户守卫（B1）：候选账号仅限目标课堂同租户——他校同学号账号
    # 不进入「已有账号加入本班」候选（V1.0 FR-03；单租户窗口行为不变）
    existing_users: dict[str, User] = {
        u.username: u
        for u in session.exec(
            select(User).where(
                col(User.username).in_(wanted_usernames),  # type: ignore[operator]
                User.tenant_id == classroom.tenant_id,
            )
        ).all()
        if u.username is not None
    }

    # 班内现有档案：绑定中的判「已在班内」；孤儿档案（被移出后 user_id 置空）
    # 按姓名找回——重新绑回账号而不是新建档案，历史 XP/作答不丢。
    # 无后缀优先；同后缀名按后缀升序保证确定性
    classroom_students = session.exec(
        select(Student)
        .where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
        .order_by(col(Student.suffix).is_not(None), col(Student.suffix))
    ).all()
    students_by_user = {
        s.user_id: s for s in classroom_students if s.user_id is not None
    }
    orphans_by_name: dict[str, Student] = {}
    for legacy in classroom_students:
        if legacy.user_id is None:
            orphans_by_name.setdefault(legacy.display_name, legacy)
    # 容量余量 = class_size - 班内现有档案数；只有新建档案才占位
    remaining_capacity = classroom.class_size - len(classroom_students)

    seen_usernames: set[str] = set()

    for line in body.lines:
        username = line.username.strip()
        full_name = line.full_name.strip()
        row = StudentImportRow(username=username, full_name=full_name)
        existing_user = existing_users.get(username)
        if not username:
            row.error = "学号为空"
        elif any(ch.isspace() for ch in username):
            row.error = "学号不能包含空格等空白字符"
        elif username in seen_usernames:
            row.error = "名单内学号重复"
        elif existing_user is not None:
            # 多班归属：同账号同名即同一学生；异名仍视为冲突阻断
            if existing_user.role != "student":
                row.error = "该学号已被非学生账号使用"
            elif existing_user.full_name and _normalized_name(
                existing_user.full_name
            ) != _normalized_name(full_name):
                row.error = "该学号已存在，但姓名与已有账号不一致，请核对名单"
        if row.error is not None:
            result.skipped += 1
            result.rows.append(row)
            continue
        seen_usernames.add(username)

        if existing_user is not None:
            enrolled = students_by_user.get(existing_user.id)
            if enrolled is not None:
                row.status = "already_enrolled"
                row.student_id = enrolled.id
                result.already_enrolled += 1
                result.rows.append(row)
                continue
            # 孤儿同名档案优先找回（保住历史）；否则常规入班，容量由 crud 兜底
            orphan = orphans_by_name.pop(full_name, None) if full_name else None
            if orphan is None and remaining_capacity <= 0:
                row.error = f"班级人数已满（上限 {classroom.class_size} 人）"
                result.skipped += 1
                result.rows.append(row)
                continue
            try:
                student = (
                    crud.join_classroom(
                        session=session,
                        classroom=classroom,
                        user=existing_user,
                        display_name=full_name,
                    )
                    if orphan is None
                    else orphan
                )
            except crud.CrossTenantJoinError:
                # 他校同号账号已不进候选，正常到不了这里；守卫兜底
                row.error = "该学号属于其他学校账号，无法加入本班"
                result.skipped += 1
                result.rows.append(row)
                continue
            except ClassroomFullError:
                row.error = f"班级人数已满（上限 {classroom.class_size} 人）"
                result.skipped += 1
                result.rows.append(row)
                continue
            if orphan is not None:
                orphan.user_id = existing_user.id
                session.add(orphan)
            else:
                remaining_capacity -= 1
            # 账号缺姓名时以名单为准补全（不影响密码/登录）
            if not existing_user.full_name:
                existing_user.full_name = full_name
                session.add(existing_user)
            row.status = "joined_existing"
            row.student_id = student.id
            result.joined += 1
            result.rows.append(row)
            continue

        # —— 新账号路径 ——
        legacy = orphans_by_name.get(full_name) if full_name else None
        if legacy is None and remaining_capacity <= 0:
            row.error = f"班级人数已满（上限 {classroom.class_size} 人）"
            result.skipped += 1
            result.rows.append(row)
            continue
        user = User(
            email=None,
            is_active=True,
            full_name=full_name or None,
            role="student",
            username=username,
            must_change_password=False,
            hashed_password=hashed_default_password,
        )
        session.add(user)
        session.flush()  # 拿 user.id 供档案绑定/查询

        # 历史匿名档案匹配：同课堂同名（优先无后缀）→ 绑定；否则新建档案。
        # 前一行绑定后从预取表摘除，同名不同学号不会重复绑同一档案
        if legacy is not None:
            orphans_by_name.pop(full_name)
            legacy.user_id = user.id
            session.add(legacy)
            student = legacy
            row.merged_existing = True
            result.merged += 1
        else:
            try:
                student = crud.join_classroom(
                    session=session,
                    classroom=classroom,
                    user=user,
                    display_name=full_name or username,
                )
            except crud.CrossTenantJoinError:
                # 他校同号账号已不进候选，正常到不了这里；守卫兜底
                row.error = "该学号属于其他学校账号，无法加入本班"
                result.skipped += 1
                result.rows.append(row)
                continue
            except ClassroomFullError:
                row.error = f"班级人数已满（上限 {classroom.class_size} 人）"
                result.skipped += 1
                result.rows.append(row)
                continue
            remaining_capacity -= 1
            result.created += 1
        row.status = "merged" if legacy is not None else "created"
        row.initial_password = DEFAULT_STUDENT_PASSWORD
        row.student_id = student.id
        result.rows.append(row)

    session.commit()
    return result


@router.get("", response_model=list[StudentAccountOut])
def list_students(
    session: SessionDep,
    current_user: TeacherUserDep,
    classroom_id: uuid.UUID = Query(...),
) -> Any:
    """课堂学生名单（带学号与改密状态）。"""
    classroom = _get_classroom_in_scope(session, current_user, classroom_id)
    students = session.exec(
        select(Student)
        .where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
        .order_by(col(Student.display_name))
    ).all()
    users_by_id = {
        u.id: u
        for u in session.exec(
            select(User).where(
                col(User.id).in_(
                    [  # type: ignore[operator]
                        s.user_id for s in students if s.user_id is not None
                    ]
                )
            )
        ).all()
    }
    out: list[StudentAccountOut] = []
    for s in students:
        u = users_by_id.get(s.user_id) if s.user_id else None
        out.append(
            StudentAccountOut(
                student=StudentPublic.model_validate(s),
                username=u.username if u else None,
                full_name=u.full_name if u else None,
                must_change_password=u.must_change_password if u else False,
            )
        )
    return out


class StudentClassroomOut(SQLModel):
    """学生在班概览（多班归属）：选班入口的班级卡片数据。"""

    classroom_id: uuid.UUID
    code: str
    name: str
    grade: str | None = None
    is_active: bool
    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    xp: int
    streak_days: int
    # 本班当前发布了练习/模考（未归档）：卡片显示「有进行中的任务」
    has_published_task: bool = False


@router.get("/me/classrooms", response_model=list[StudentClassroomOut])
def list_my_enrollments(
    session: SessionDep,
    current_user: StudentUserDep,
) -> Any:
    """学生本人已加入的全部班级（多班归属）：登录后选班入口。

    只返回在用课堂；管理员停用的课堂不出现。成长数据（XP/连胜）按班内
    档案各自独立，卡片展示各班的。
    """
    rows = session.exec(
        select(Student, Classroom)
        .join(
            Classroom,
            Classroom.id == Student.classroom_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            Student.user_id == current_user.id,  # type: ignore[arg-type]
            col(Classroom.is_active).is_(True),
        )
        .order_by(col(Student.created_at))
    ).all()
    exercise_ids = [
        classroom.current_exercise_id
        for _, classroom in rows
        if classroom.current_exercise_id is not None
    ]
    live_exercise_ids: set[uuid.UUID] = set()
    if exercise_ids:
        live_exercise_ids = {
            exercise.id
            for exercise in session.exec(
                select(ClassroomExercise).where(
                    col(ClassroomExercise.id).in_(exercise_ids),  # type: ignore[operator]
                    col(ClassroomExercise.status) == "published",
                    col(ClassroomExercise.archived_at).is_(None),
                )
            ).all()
        }
    return [
        StudentClassroomOut(
            classroom_id=classroom.id,
            code=classroom.code,
            name=classroom.name,
            grade=classroom.grade,
            is_active=classroom.is_active,
            student_id=student.id,
            display_name=student.display_name,
            suffix=student.suffix,
            xp=student.xp,
            streak_days=student.streak_days,
            has_published_task=(
                classroom.current_exercise_id in live_exercise_ids
                if classroom.current_exercise_id is not None
                else False
            ),
        )
        for student, classroom in rows
    ]


@router.post("/{student_id}/reset-password")
def reset_student_password(
    session: SessionDep,
    current_user: TeacherUserDep,
    student_id: uuid.UUID,
) -> dict[str, str]:
    """重置学生密码：恢复为统一默认密码（学生登录后可自行修改）。"""
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _get_classroom_in_scope(session, current_user, student.classroom_id)
    if student.user_id is None:
        raise HTTPException(status_code=422, detail="该学生档案未绑定账号")
    user = session.get(User, student.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _ensure_account_reset_allowed(
        session, current_user, user, classroom_id=student.classroom_id
    )
    logger.info(
        "password reset by teacher=%s target_user=%s student=%s classroom=%s",
        current_user.id,
        user.id,
        student.id,
        student.classroom_id,
    )
    user.hashed_password = get_password_hash(DEFAULT_STUDENT_PASSWORD)
    user.must_change_password = False
    session.add(user)
    session.commit()
    return {"new_password": DEFAULT_STUDENT_PASSWORD}


class StudentResetRow(SQLModel):
    username: str
    full_name: str | None = None
    student_id: uuid.UUID
    new_password: str


class BulkResetResult(SQLModel):
    reset: int
    skipped: int = 0
    rows: list[StudentResetRow]


@router.post("/bulk-reset-password", response_model=BulkResetResult)
def bulk_reset_passwords(
    session: SessionDep,
    current_user: TeacherUserDep,
    classroom_id: uuid.UUID = Query(...),
) -> Any:
    """批量重置课堂内全部已绑定账号的密码为统一默认密码。

    账号级守卫与单条重置一致（非学生账号 / 名下档案跨其他教师班级的一律
    跳过并计入 skipped），避免批量入口绕过凭证范围检查。
    """
    classroom = _get_classroom_in_scope(session, current_user, classroom_id)
    students = session.exec(
        select(Student)
        .where(
            Student.classroom_id == classroom.id,  # type: ignore[arg-type]
            col(Student.user_id).is_not(None),
        )
        .order_by(col(Student.display_name))
    ).all()
    user_ids = [s.user_id for s in students if s.user_id is not None]
    users_by_id = {
        u.id: u
        for u in session.exec(
            select(User).where(col(User.id).in_(user_ids))  # type: ignore[operator]
        ).all()
    }
    result = BulkResetResult(reset=0, skipped=0, rows=[])
    # 统一默认密码只做一次 argon2 哈希（与导入路径同款优化；60 人班逐人
    # 哈希会秒级持有写事务）。守卫与 _ensure_account_reset_allowed 同口径
    # （角色单源+跨班归属须本人），批量入口一次预取跨班归属，
    # 不在循环里逐人查询——两处口径必须同步改
    shared_hash = get_password_hash(DEFAULT_STUDENT_PASSWORD)
    cross_owner_user_ids: set[uuid.UUID] = set()
    if user_ids and current_user.role != "admin":
        cross_owner_user_ids = {
            user_id
            for user_id, owner_id in session.exec(
                select(Student.user_id, Classroom.owner_id)
                .join(Classroom)
                .where(
                    col(Student.user_id).in_(user_ids),  # type: ignore[operator]
                    Student.classroom_id != classroom.id,  # type: ignore[arg-type]
                )
            ).all()
            if user_id is not None and owner_id != current_user.id
        }
    for s in students:
        user = users_by_id.get(s.user_id) if s.user_id else None
        if user is None:
            continue
        if user.role != "student" or user.id in cross_owner_user_ids:
            result.skipped += 1
            logger.info(
                "bulk password reset skipped target_user=%s student=%s classroom=%s",
                user.id,
                s.id,
                classroom.id,
            )
            continue
        user.hashed_password = shared_hash
        user.must_change_password = False
        session.add(user)
        result.rows.append(
            StudentResetRow(
                username=user.username or "",
                full_name=user.full_name,
                student_id=s.id,
                new_password=DEFAULT_STUDENT_PASSWORD,
            )
        )
        result.reset += 1
    session.commit()
    return result
