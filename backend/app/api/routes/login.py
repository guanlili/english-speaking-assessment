from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import SQLModel

from app import crud
from app.api.deps import (
    CurrentUser,
    PlatformOperatorDep,
    SessionDep,
    get_current_platform_operator,
)
from app.core import security
from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter
from app.models import (
    Message,
    NewPassword,
    PlatformOperatorPublic,
    Token,
    UserPublic,
    UserUpdate,
)
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


class SchoolLoginInfo(SQLModel):
    """学校入口受限读取（V1.0 FR-02）：仅登录页展示所需字段，不含账号信息。"""

    slug: str
    name_zh: str
    name_en: str | None = None


@router.get("/login/school/{slug}", response_model=SchoolLoginInfo)
def read_school_login_info(slug: str, response: Response) -> SchoolLoginInfo:
    # 公开端点（登录引导）：no-store 防缓存学校枚举；未知/停用统一 404
    response.headers["Cache-Control"] = "no-store"
    from sqlmodel import Session as _Session
    from sqlmodel import select as _select

    from app.core.db import engine as _engine
    from app.models import Tenant

    with _Session(_engine) as session:
        tenant = session.exec(
            _select(Tenant).where(Tenant.slug == slug.strip().lower())
        ).first()
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=404, detail="学校不存在或未开放")
    return SchoolLoginInfo(
        slug=tenant.slug, name_zh=tenant.name_zh, name_en=tenant.name_en
    )


@router.post("/login/access-token")
def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    school: str | None = Query(default=None, description="学校码（多租户 B2）"),
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests.

    多租户 B2：school 查询参数可选——传入则按 (租户, 标识) 限定查找，
    两校同号各自登录；不传则全局查找（单校窗口兼容）。用 Query 而非
    表单字段：不干预 OAuth2 标准表单解析，兼容性最稳。
    """
    client_ip = request.client.host if request.client else "unknown"
    # 双维度限流：IP 桶（NAT 出口共享，防横向刷）+ 账号桶（防针对单账号爆破）。
    # IP 取自 uvicorn 解析的 X-Forwarded-For（compose 已设 FORWARDED_ALLOW_IPS，
    # nginx 是唯一上游；多 worker 部署时内存字典各进程独立，限额按 worker 数放大）
    account = form_data.username.strip().lower()
    _check_login_rate_limit(f"ip:{client_ip}")
    _check_login_rate_limit(f"user:{account}")

    # 未知学校/密码错误/跨租户歧义统一同文案——不泄露存在性（AC-01/03）
    school_slug = school.strip().lower() if school else None
    user = crud.authenticate(
        session=session,
        account=form_data.username.strip(),
        password=form_data.password,
        school_slug=school_slug,
    )
    if not user:
        raise HTTPException(status_code=400, detail="账号或密码不正确")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # 账号桶整桶清空（成功即本人）；IP 桶只退还本次占用的额度、保留
    # 失败计数——NAT 出口共享，成功清桶会让「喷洒+成功」交替绕过限流
    _login_limiter.record_success(f"ip:{client_ip}", refund_only=True)
    _record_login_success(f"user:{account}")
    return Token(
        access_token=security.create_access_token(
            user.id,
            expires_delta=access_token_expires,
            role=user.role,
            password_hash=user.hashed_password,
            tenant_id=str(user.tenant_id),
        )
    )


@router.post("/login/platform-token")
def login_platform_token(
    request: Request,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """平台运营登录（多租户 B3）：独立身份 + 独立 audience（设计稿 §3.2）。

    签发 typ=operator/aud=platform 的 token——只被平台运营门接受，
    学校用户端点一律拒收（deps.get_current_user）。与学校登录共用
    限流器但分桶计数。
    """
    client_ip = request.client.host if request.client else "unknown"
    account = form_data.username.strip().lower()
    _check_login_rate_limit(f"ip:{client_ip}")
    _check_login_rate_limit(f"op:{account}")
    operator = crud.authenticate_platform_operator(
        session=session, email=form_data.username.strip(), password=form_data.password
    )
    if not operator:
        raise HTTPException(status_code=400, detail="账号或密码不正确")
    if not operator.is_active:
        raise HTTPException(status_code=400, detail="Inactive operator")
    _login_limiter.record_success(f"ip:{client_ip}", refund_only=True)
    _record_login_success(f"op:{account}")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            operator.id,
            expires_delta=access_token_expires,
            role="operator",
            password_hash=operator.hashed_password,
            audience="platform",
            token_type="operator",
        )
    )


@router.get("/login/platform/me", response_model=PlatformOperatorPublic)
def read_platform_operator_me(
    response: Response, operator: PlatformOperatorDep
) -> PlatformOperatorPublic:
    """运营自述（前端运营会话的 currentUser 等价物）：仅展示字段。"""
    response.headers["Cache-Control"] = "no-store"
    return PlatformOperatorPublic(email=operator.email, full_name=operator.full_name)


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


@router.post("/login/platform-demo")
def login_platform_demo(session: SessionDep) -> Token:
    """运营演示登录（仅 local）：为种子运营账号直接签发 operator token。

    与 /login/demo（学校侧）对偶——B3 身份拆分后平台页（大盘/单元/
    句型库/用户管理）只认运营身份，e2e 与本地演示需要一键运营会话。
    """
    if settings.ENVIRONMENT != "local":
        raise HTTPException(status_code=404, detail="Not Found")
    from sqlmodel import select as _select

    from app.models import PlatformOperator

    operator = session.exec(
        _select(PlatformOperator).where(
            PlatformOperator.email == settings.first_operator_email
        )
    ).first()
    if operator is None or not operator.is_active:
        raise HTTPException(status_code=404, detail="Not Found")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            operator.id,
            expires_delta=access_token_expires,
            role="operator",
            password_hash=operator.hashed_password,
            audience="platform",
            token_type="operator",
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
    dependencies=[Depends(get_current_platform_operator)],
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
