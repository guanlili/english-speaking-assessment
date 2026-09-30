from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"

# 三级角色：admin（=is_superuser）/ teacher / student
VALID_ROLES = {"admin", "teacher", "student"}


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta,
    role: str | None = None,
    password_hash: str = "",
) -> str:
    expire = datetime.now(UTC) + expires_delta
    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject)}
    if role is not None:
        # 角色随 token 下发供前端分流；权限判定始终查库
        to_encode["role"] = role
    if password_hash:
        # 密码哈希指纹绑定：改密/重置后旧 token 立即失效
        to_encode["pwd"] = password_fingerprint(password_hash)
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def password_fingerprint(hashed_password: str) -> str:
    """密码哈希指纹：绑定进 token，改密后与库中不一致即失效。

    取 [:48] 是有讲究的——argon2/bcrypt 哈希的开头是固定的算法参数头
    （如 `$argon2id$v=19$m=65536,t=3,p=4$` 约 31 字符），截太短不同密码的
    指纹相同（起不到绑定作用），48 字符已进入随机盐区间。
    """
    return hashed_password[:48]


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


# 学生账号统一默认密码（学校统一发放，学生登录后可自行修改）
DEFAULT_STUDENT_PASSWORD = "brs123456"
