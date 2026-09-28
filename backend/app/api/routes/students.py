"""学生账号管理：批量导入（学号+姓名→初始密码）、名单、重置密码、移出课堂。

权限：管理员任意课堂；教师仅自己名下课堂。
导入时按「课堂+姓名」自动匹配历史匿名学生档案，把 XP/作答历史绑到新账号。
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
from sqlmodel import Session, SQLModel, col, select

from app import crud
from app.api.deps import SessionDep, TeacherUserDep
from app.core.security import DEFAULT_STUDENT_PASSWORD, get_password_hash
from app.models import (
    Classroom,
    Student,
    StudentPublic,
    User,
)

router = APIRouter(prefix="/students", tags=["students"])


def _get_classroom_in_scope(
    session: Session, current_user: User, classroom_id: uuid.UUID
) -> Classroom:
    classroom = session.get(Classroom, classroom_id)
    if classroom is None or not classroom.is_active:
        raise HTTPException(status_code=404, detail="Classroom not found")
    if not current_user.is_superuser and classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="没有权限：只能管理自己课堂的学生")
    return classroom


class StudentImportLine(SQLModel):
    username: str = Field(max_length=64)
    full_name: str = Field(max_length=255)


class StudentImportRequest(SQLModel):
    classroom_id: uuid.UUID
    lines: list[StudentImportLine]


class StudentImportRow(SQLModel):
    """导入结果行：初始密码只在本次响应返回一次，不入日志。"""

    username: str
    full_name: str
    initial_password: str | None = None
    student_id: uuid.UUID | None = None
    # 命中的历史匿名档案：XP/作答历史绑定到该账号
    merged_existing: bool = False
    error: str | None = None


class StudentImportResult(SQLModel):
    created: int
    merged: int
    skipped: int
    rows: list[StudentImportRow]


class StudentAccountOut(SQLModel):
    student: StudentPublic
    username: str | None = None
    full_name: str | None = None
    must_change_password: bool = False


@router.post("/import", response_model=StudentImportResult)
def import_students(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: StudentImportRequest,
) -> Any:
    """批量导入学生：每行「学号 姓名」；已有学号跳过并提示。

    同名历史匿名档案自动绑定（保留 XP/作答）；密码统一为默认密码。
    """
    classroom = _get_classroom_in_scope(session, current_user, body.classroom_id)
    result = StudentImportResult(created=0, merged=0, skipped=0, rows=[])
    seen_usernames: set[str] = set()

    for line in body.lines:
        username = line.username.strip()
        full_name = line.full_name.strip()
        row = StudentImportRow(username=username, full_name=full_name)
        if not username:
            row.error = "学号为空"
        elif username in seen_usernames:
            row.error = "名单内学号重复"
        elif (
            session.exec(
                select(User).where(User.username == username)  # type: ignore[arg-type]
            ).first()
            is not None
        ):
            row.error = "该学号已存在（已导入过或与现有账号冲突）"
        if row.error is not None:
            result.skipped += 1
            result.rows.append(row)
            continue
        seen_usernames.add(username)

        user = User(
            email=None,
            is_active=True,
            is_superuser=False,
            full_name=full_name or None,
            role="student",
            username=username,
            must_change_password=False,
            hashed_password=get_password_hash(DEFAULT_STUDENT_PASSWORD),
        )
        session.add(user)
        session.flush()  # 拿 user.id 供档案绑定/查询

        # 历史匿名档案匹配：同课堂同名（优先无后缀）→ 绑定；否则新建档案
        legacy = session.exec(
            select(Student)
            .where(
                Student.classroom_id == classroom.id,  # type: ignore[arg-type]
                Student.display_name == full_name,  # type: ignore[arg-type]
                col(Student.user_id).is_(None),
            )
            .order_by(col(Student.suffix).is_not(None))  # 无后缀优先
            .limit(1)
        ).first()
        if legacy is not None:
            legacy.user_id = user.id
            session.add(legacy)
            student = legacy
            row.merged_existing = True
            result.merged += 1
        else:
            student = crud.join_classroom(
                session=session,
                classroom=classroom,
                user=user,
                display_name=full_name or username,
            )
            result.created += 1
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
    user.hashed_password = get_password_hash(DEFAULT_STUDENT_PASSWORD)
    user.must_change_password = False
    session.add(user)
    session.commit()
    return {"new_password": DEFAULT_STUDENT_PASSWORD}


@router.delete("/{student_id}")
def remove_student(
    session: SessionDep,
    current_user: TeacherUserDep,
    student_id: uuid.UUID,
) -> dict[str, str]:
    """把学生移出课堂：档案与作答历史保留（可重新导入找回），仅解除账号绑定。"""
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    _get_classroom_in_scope(session, current_user, student.classroom_id)
    student.user_id = None
    session.add(student)
    session.commit()
    return {"message": "已移出课堂（档案与历史保留，重新导入可找回）"}


class StudentResetRow(SQLModel):
    username: str
    full_name: str | None = None
    student_id: uuid.UUID
    new_password: str


class BulkResetResult(SQLModel):
    reset: int
    rows: list[StudentResetRow]


@router.post("/bulk-reset-password", response_model=BulkResetResult)
def bulk_reset_passwords(
    session: SessionDep,
    current_user: TeacherUserDep,
    classroom_id: uuid.UUID = Query(...),
) -> Any:
    """批量重置课堂内全部已绑定账号的密码为统一默认密码。"""
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
    result = BulkResetResult(reset=0, rows=[])
    for s in students:
        user = users_by_id.get(s.user_id) if s.user_id else None
        if user is None:
            continue
        user.hashed_password = get_password_hash(DEFAULT_STUDENT_PASSWORD)
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
