import uuid
from collections.abc import Callable, Generator
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import db as _db
from app.core import security
from app.core.config import settings
from app.models import PlatformOperator, TokenPayload, User

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


def get_export_submitter() -> Callable[[uuid.UUID], None]:
    """原音频 ZIP 任务提交器。测试可覆写为同步执行。"""
    from app.exporting.worker import submit_export_job

    return submit_export_job


ExportSubmitter = Annotated[Callable[[uuid.UUID], None], Depends(get_export_submitter)]


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
    # B3 身份拆分：运营 token（独立 audience）不能当学校用户用——学校
    # 身份与运营身份互不冒用（设计稿 §3.2）
    if token_data.typ == "operator":
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
    # token 绑定签发时的密码哈希指纹：改密/重置后旧 token 失效（含不带 pwd 声明的旧格式 token）
    if token_data.pwd != security.password_fingerprint(user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_platform_operator(
    session: SessionDep, token: TokenDep
) -> PlatformOperator:
    """平台运营门（多租户 B3）：独立身份 + 独立 audience 凭证（设计稿 §3.2）。

    只认 typ=operator 的运营 token；学校用户 token 到这里一律 403
    （已认证但身份不符），token 无效/过期仍是 401。运营账号状态与
    密码指纹实时查库——停用/改密立即生效，不等 token 自然过期。
    """
    try:
        # 独立 audience 校验（JWT 规范路径）：学校 token 无 aud 声明，
        # 在此直接 InvalidAudienceError → 401；运营 token 必须 aud=platform
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM],
            audience="platform",
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):  # fmt: skip
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token_data.typ != "operator":
        raise HTTPException(status_code=403, detail="该操作需要平台运营身份")
    operator = session.get(PlatformOperator, token_data.sub)
    if operator is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token_data.pwd != security.password_fingerprint(operator.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not operator.is_active:
        raise HTTPException(status_code=403, detail="Inactive operator")
    return operator


PlatformOperatorDep = Annotated[
    PlatformOperator, Depends(get_current_platform_operator)
]


def _require_role(current_user: User, *allowed: str) -> User:
    """角色门：校级 admin 恒通过（校级管理员 ⇔ role=="admin"，B3 起无全局超管）。"""
    if current_user.role == "admin" or current_user.role in allowed:
        return current_user
    raise HTTPException(status_code=403, detail=f"该操作需要角色：{'/'.join(allowed)}")


def get_current_teacher(current_user: CurrentUser) -> User:
    """教师或校级管理员（内容/课堂/学生账号管理类操作）。"""
    return _require_role(current_user, "teacher")


def get_current_student(current_user: CurrentUser) -> User:
    """仅学生（学生端练习链路）。"""
    if current_user.role != "student" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="该操作仅限学生账号")
    return current_user


def get_current_staff_or_operator(
    session: SessionDep, token: TokenDep
) -> User | PlatformOperator:
    """多态身份门（B3）：学校教职工（teacher/admin）或平台运营任一即可。

    用于「平台发布、两类身份都要读」的端点（更新日志列表）。一次解码后
    按 typ 声明分流：运营 token 走运营表校验，学校 token 走用户表校验；
    token 无效/过期仍是 401，身份不符是 403。
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM],
            options={"verify_aud": False},
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):  # fmt: skip
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token_data.typ == "operator":
        operator = session.get(PlatformOperator, token_data.sub)
        if operator is None or token_data.pwd != security.password_fingerprint(
            operator.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not operator.is_active:
            raise HTTPException(status_code=403, detail="Inactive operator")
        return operator
    user = session.get(User, token_data.sub)
    if user is None or token_data.pwd != security.password_fingerprint(
        user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="该操作需要教职工或平台运营身份")
    return user


# 注意：别名类型用 Any——User | PlatformOperator 的 union 会被 FastAPI
# 当成请求体模型解析（GET 无 body → 422），依赖注入只关心函数不看注解
StaffOrOperatorDep = Annotated[Any, Depends(get_current_staff_or_operator)]


TeacherUserDep = Annotated[User, Depends(get_current_teacher)]
StudentUserDep = Annotated[User, Depends(get_current_student)]


def get_optional_current_user(
    session: SessionDep, token: str | None = Depends(reusable_oauth2_optional)
) -> User | None:
    """可选登录：无 Authorization / token 无效时返回 None（不报 401）。

    用于「学生凭证或教师凭证二选一」的端点（如音频回放）。
    运营 token（typ=operator）不是学校身份，同样按匿名处理。
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
    if token_data.typ == "operator":
        return None
    user = session.get(User, token_data.sub)
    if user is None or not user.is_active:
        return None
    # 改密后的旧 token 同样按无效处理（与 get_current_user 一致，只是静默降级为匿名）
    if token_data.pwd != security.password_fingerprint(user.hashed_password):
        return None
    return user


OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]
