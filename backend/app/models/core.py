"""租户/用户模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import uuid
from datetime import datetime

from pydantic import EmailStr
from sqlalchemy import (
    DateTime,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    _tenant_id_field,
    get_datetime_utc,
)


class Tenant(SQLModel, table=True):
    """租户=一所独立管理的学校（V1.0 §2）。原校标识须由管理员核实后改名。"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=32)
    name_zh: str = Field(max_length=120)
    name_en: str | None = Field(default=None, max_length=120)
    # 生命周期首两态先落地；其余四态随 D 期学校运营补齐
    status: str = Field(default="active", max_length=16, index=True)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class PlatformOperator(SQLModel, table=True):
    """平台运营独立身份（多租户 B3，设计稿 §3.2/§4.1）。

    与学校 User 完全分离：独立表、独立登录端点（/login/platform-token）、
    独立 token 身份（typ=operator + aud=platform）。学校侧自此没有
    全局绕过身份——User.is_superuser 已移除，旧「admin」即校级管理员
    （设计稿：不把旧管理员自动升级为跨校运营）。
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Shared properties
class UserBase(SQLModel):
    # 学生无邮箱：email 可空（学号登录），教师/管理员必填（API 层校验）。
    # 唯一性由 (tenant_id, email) 复合承接（B2 去全局唯一——两校可同邮箱）
    email: EmailStr | None = Field(default=None, index=True, max_length=255)
    is_active: bool = True
    full_name: str | None = Field(default=None, max_length=255)
    # 校级三角色：admin（校级管理员）/ teacher / student。
    # B3 起学校侧不再有跨校绕过身份（is_superuser 已随 PlatformOperator
    # 拆分移除）；平台运营见 PlatformOperator 表（设计稿 §3.2）
    role: str = Field(default="teacher", max_length=16, index=True)
    # 学号（student 登录名）；教师/管理员为空。唯一性由
    # (tenant_id, username) 复合承接（B2 起两校可同号——多租户前提）
    username: str | None = Field(default=None, index=True, max_length=64)
    # 批量导入的初始密码标记：首登后前端强制改密，改密接口清位
    must_change_password: bool = Field(default=False)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: str | None = Field(default=None, max_length=16)
    username: str | None = Field(default=None, max_length=64)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 租户归属：B1 起列级默认兜底（ORM default + server_default 双保险），
    # 全表 NOT NULL——存量由迁移回填，增量不可能漏写
    tenant_id: uuid.UUID = _tenant_id_field()
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )

    # 校内唯一（登录解析走 (tenant_id, 标识)，见 B2）；旧的全局唯一索引
    # 在单校窗口内与复合唯一等价，收紧期（设计稿 §9-5）随登录改造一并移除
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    # 所属学校（D2 运营视角：用户管理的学校维度；学校侧端点恒为本校）
    tenant_id: uuid.UUID | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class PlatformOperatorPublic(SQLModel):
    """平台运营自述（/login/platform/me）：只暴露展示所需字段。"""

    email: EmailStr
    full_name: str | None = None


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None
    # 登录角色随 token 下发，前端按角色分流（不作为权限依据，权限查库）
    role: str | None = None
    # 签发时的密码哈希前缀：与库中不一致（改密/重置过）则 token 失效
    pwd: str | None = None
    # 多租户 B2：签发时的租户（旧 token 无此字段=单校窗口兼容）；
    # 前端用于学校上下文展示，归属判定仍查库
    tid: str | None = None
    # 多租户 B3 身份拆分：平台运营 token 携带 typ=operator + aud=platform；
    # 学校用户 token 不带这两个字段（独立 audience，设计稿 §3.2）。
    # get_current_user 拒收 operator token，学校身份不得被运营凭证冒用
    typ: str | None = None
    aud: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
