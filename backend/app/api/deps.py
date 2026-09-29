import uuid
from collections.abc import Callable, Generator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import db as _db
from app.core import security
from app.core.config import settings
from app.models import TokenPayload, User

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)
# 可选登录用：没带 Authorization 头时不报错，交回 None 由端点走学生凭证通道
reusable_oauth2_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=False
)


def get_db() -> Generator[Session]:
    # 每次请求解析 engine，保证测试 set_engine() 覆盖生效
    with Session(_db.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def get_scoring_submitter() -> Callable[[uuid.UUID], None]:
    """评分任务提交器。测试里覆写为同步执行以走完整个状态机。"""
    from app.scoring.worker import submit_attempt_scoring

    return submit_attempt_scoring


ScoringSubmitter = Annotated[
    Callable[[uuid.UUID], None], Depends(get_scoring_submitter)
]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):  # fmt: skip
        # 401 = token 无效/过期（前端据此登出）；403 留给"已登录但权限不足"，二者不可混用
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


SuperUserDep = Annotated[User, Depends(get_current_active_superuser)]


def _require_role(current_user: User, *allowed: str) -> User:
    """角色门：admin 恒通过（admin ⇔ is_superuser 的不变量见 models.UserBase）。"""
    if current_user.is_superuser or current_user.role in allowed:
        return current_user
    raise HTTPException(status_code=403, detail=f"该操作需要角色：{'/'.join(allowed)}")


def get_current_teacher(current_user: CurrentUser) -> User:
    """教师或管理员（内容/课堂/学生账号管理类操作）。"""
    return _require_role(current_user, "teacher")


def get_current_student(current_user: CurrentUser) -> User:
    """仅学生（学生端练习链路）。"""
    if not current_user.is_superuser and current_user.role != "student":
        raise HTTPException(status_code=403, detail="该操作仅限学生账号")
    return current_user


TeacherUserDep = Annotated[User, Depends(get_current_teacher)]
StudentUserDep = Annotated[User, Depends(get_current_student)]


def get_optional_current_user(
    session: SessionDep, token: str | None = Depends(reusable_oauth2_optional)
) -> User | None:
    """可选登录：无 Authorization / token 无效时返回 None（不报 401）。

    用于「学生凭证或教师凭证二选一」的端点（如音频回放）。
    """
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):  # fmt: skip
        return None
    user = session.get(User, token_data.sub)
    if user is None or not user.is_active:
        return None
    return user


OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]
