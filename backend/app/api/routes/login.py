from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import SQLModel

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core import security
from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter
from app.models import Message, NewPassword, Token, UserPublic, UserUpdate
from app.utils import (
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_password_reset_token,
)

_login_limiter = SlidingWindowLimiter(limit=10, window_s=300)
# 兼容旧测试钩子：test_login 直接 clear 该 dict / 持锁操作清理用例间状态
_login_attempts = _login_limiter._attempts  # noqa: SLF001
_login_lock = _login_limiter._lock  # noqa: SLF001
LOGIN_RATE_LIMIT = 10
LOGIN_RATE_WINDOW_S = 300


def _check_login_rate_limit(bucket: str) -> None:
    _login_limiter.check(bucket, detail="登录尝试过于频繁，请 5 分钟后再试")


def _record_login_success(bucket: str) -> None:
    _login_limiter.record_success(bucket)


router = APIRouter(tags=["login"])


class LoginOptions(SQLModel):
    demo_enabled: bool
    registration_enabled: bool
    password_recovery_enabled: bool


@router.get("/login/options", response_model=LoginOptions)
def read_login_options(response: Response) -> LoginOptions:
    response.headers["Cache-Control"] = "no-store"
    return LoginOptions(
        demo_enabled=settings.ENVIRONMENT == "local",
        registration_enabled=settings.USERS_OPEN_REGISTRATION,
        password_recovery_enabled=settings.emails_enabled,
    )


@router.post("/login/access-token")
def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    client_ip = request.client.host if request.client else "unknown"
    # 双维度限流：IP 桶（NAT 出口共享，防横向刷）+ 账号桶（防针对单账号爆破）。
    # IP 取自 uvicorn 解析的 X-Forwarded-For（compose 已设 FORWARDED_ALLOW_IPS，
    # nginx 是唯一上游；多 worker 部署时内存字典各进程独立，限额按 worker 数放大）
    account = form_data.username.strip().lower()
    _check_login_rate_limit(f"ip:{client_ip}")
    _check_login_rate_limit(f"user:{account}")

    user = crud.authenticate(
        session=session, account=form_data.username.strip(), password=form_data.password
    )
    if not user:
        raise HTTPException(status_code=400, detail="账号或密码不正确")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    _record_login_success(f"ip:{client_ip}")
    _record_login_success(f"user:{account}")
    return Token(
        access_token=security.create_access_token(
            user.id,
            expires_delta=access_token_expires,
            role=user.role,
            password_hash=user.hashed_password,
        )
    )


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/login/demo")
def login_demo(session: SessionDep) -> Token:
    """演示视角快捷登录：为内置管理员直接签发 token。

    仅在 ENVIRONMENT=local 开放（登录页三角色入口用）；
    生产/预发环境一律 404，不暴露任何凭据。
    """
    if settings.ENVIRONMENT != "local":
        raise HTTPException(status_code=404, detail="Not Found")
    user = crud.get_user_by_email(session=session, email=settings.FIRST_SUPERUSER)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="Not Found")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id,
            expires_delta=access_token_expires,
            role=user.role,
            password_hash=user.hashed_password,
        )
    )


@router.post("/password-recovery/{email}")
def recover_password(email: str, request: Request, session: SessionDep) -> Message:
    """
    Password Recovery
    """
    # 匿名可达的发信入口，必须限流防邮件轰炸：IP 桶防横向刷 + 邮箱桶防针对
    # 单箱轰炸（复用登录限流的窗口/上限）。服务未启用时同样计数，
    # 不给探测方留下「换邮箱试探可用性」的空间
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(f"recovery:ip:{client_ip}")
    _check_login_rate_limit(f"recovery:email:{email.strip().lower()}")
    # 学生无邮箱（学号登录），该通道天然只服务教师/管理员
    # 在查询账号前统一检查，服务不可用时也不能泄露邮箱是否已注册。
    if not settings.emails_enabled:
        raise HTTPException(
            status_code=503, detail="邮件找回暂不可用，请联系学校管理员重置密码"
        )
    user = crud.get_user_by_email(session=session, email=email)
    if user:
        password_reset_token = generate_password_reset_token(
            email=email, password_hash=user.hashed_password
        )
        email_to = user.email or email  # 按邮箱查到的账号，email 必非空
        email_data = generate_reset_password_email(
            email_to=email_to, email=email, token=password_reset_token
        )
        send_email(
            email_to=email_to,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """
    Reset password
    """
    email = verify_password_reset_token(token=body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = crud.get_user_by_email(session=session, email=email)
    if not user or not user.is_active:
        # 不暴露账号是否存在；用同一错误避免信息泄露
        raise HTTPException(status_code=400, detail="Invalid token")
    # token 中密码哈希前缀与当前不一致 → token 已被用过后改密了，拒绝复用
    if not verify_password_reset_token(
        token=body.token, password_hash=user.hashed_password
    ):
        raise HTTPException(status_code=400, detail="Invalid token")
    user_in_update = UserUpdate(password=body.new_password)
    crud.update_user(
        session=session,
        db_user=user,
        user_in=user_in_update,
    )
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """
    HTML Content for Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(
        email=email, password_hash=user.hashed_password
    )
    email_data = generate_reset_password_email(
        email_to=user.email or email, email=email, token=password_reset_token
    )

    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )
