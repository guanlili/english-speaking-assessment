"""四角色完善：学校管理员管理本校成员（教师/管理员账号）.

此前建教师要找平台管理员——接多校后乙校加老师会被平台侧卡住。
本路由把该能力下放给本校 school_admin（D 期学校运营第二块面）：

- 全部操作显式限定 `tenant_id == 当前管理员所属学校`——user 表属
  身份层无 RLS（登录天然跨租户），租户边界必须在这里守住
- 建号仅限教师角色（school_admin 的创建/升降级仍归平台——避免
  任意校级管理员自行复制管理员权限）
- 停用优先于删除；不改邮箱/角色（最小面，需要时再扩）
- 密码重置：与学生批量重置同款审计语义，仅本校目标
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Field, SQLModel, col, select
from sqlmodel import Session as SASession

from app import crud
from app.api.deps import CurrentUser, SessionDep
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import get_password_hash
from app.models import User, UserCreate, UserPublic

router = APIRouter(prefix="/school/members", tags=["school"])

_member_limiter = SlidingWindowLimiter(limit=20, window_s=300)


def _require_school_admin(current_user: CurrentUser) -> User:
    if current_user.role != "school_admin":
        raise HTTPException(status_code=403, detail="该操作仅限学校管理员")
    return current_user


SchoolAdminDep = Annotated[User, Depends(_require_school_admin)]


class MemberCreate(SQLModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class MemberUpdate(SQLModel):
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


def _own_tenant_member_or_404(
    session: SASession, current_user: User, user_id: uuid.UUID
) -> User:
    target = session.get(User, user_id)
    # 跨校目标按不存在处理（不泄露他校账号存在性）
    if target is None or target.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.role == "student":
        # 学生账号走课堂导入/名册管理，不在此重复入口
        raise HTTPException(status_code=422, detail="学生账号请在「我的课堂」内管理")
    return target


class MembersPublic(SQLModel):
    data: list[UserPublic]
    count: int


@router.get("", response_model=MembersPublic)
def list_members(
    session: SessionDep,
    current_user: SchoolAdminDep,
    q: str | None = Query(default=None, max_length=128),
    role: str | None = Query(default=None, max_length=16),
) -> Any:
    """本校教师与管理员列表（学号/姓名/邮箱搜索、角色筛选）。"""
    conditions = [User.tenant_id == current_user.tenant_id]
    conditions.append(col(User.role).in_(["teacher", "school_admin"]))  # type: ignore[union-attr]
    if q and q.strip():
        conditions.append(
            col(User.email).icontains(q.strip())  # type: ignore[union-attr]
            | col(User.full_name).icontains(q.strip())  # type: ignore[union-attr]
        )
    if role:
        conditions.append(User.role == role)
    rows = session.exec(
        select(User)
        .where(*conditions)
        .order_by(col(User.created_at).desc(), col(User.id))
        .limit(200)
    ).all()
    return {
        "data": [UserPublic.model_validate(r) for r in rows],
        "count": len(rows),
    }


@router.post("", response_model=UserPublic)
def create_member(
    session: SessionDep,
    current_user: SchoolAdminDep,
    member_in: MemberCreate,
) -> Any:
    """给本校建教师账号（tenant 显式钉死本校，与请求上下文双保险）。"""
    email = member_in.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="教师账号必须提供邮箱")
    _member_limiter.check(f"create:{current_user.id}")
    existing = crud.get_user_by_email(
        session=session, email=email, tenant_id=current_user.tenant_id
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = crud.create_user(
        session=session,
        user_create=UserCreate(
            email=email,
            password=member_in.password,
            full_name=member_in.full_name,
            role="teacher",
        ),
        tenant_id=current_user.tenant_id,
    )
    return user


@router.patch("/{user_id}", response_model=UserPublic)
def update_member(
    session: SessionDep,
    current_user: SchoolAdminDep,
    user_id: uuid.UUID,
    member_in: MemberUpdate,
) -> Any:
    """停用/启用、重置密码（仅本校非学生成员；不可自停用）。"""
    target = _own_tenant_member_or_404(session, current_user, user_id)
    update = member_in.model_dump(exclude_unset=True)
    if update.get("is_active") is False and target.id == current_user.id:
        raise HTTPException(status_code=422, detail="不能停用自己的账号")
    if "password" in update:
        update["password"] = member_in.password or ""
    # 直接落库（不走 crud.update_user 的通用路径：字段白名单在此收紧）
    payload: dict[str, Any] = {}
    if "is_active" in update:
        payload["is_active"] = update["is_active"]
    if "password" in update and update["password"]:
        payload["hashed_password"] = get_password_hash(update["password"])
    if not payload:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    target.sqlmodel_update(payload)
    session.add(target)
    session.commit()
    session.refresh(target)
    return target
