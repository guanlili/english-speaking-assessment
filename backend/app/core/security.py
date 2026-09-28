import hashlib
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
    subject: str | Any, expires_delta: timedelta, role: str | None = None
) -> str:
    expire = datetime.now(UTC) + expires_delta
    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject)}
    if role is not None:
        # 角色随 token 下发供前端分流；权限判定始终查库
        to_encode["role"] = role
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def generate_initial_password() -> str:
    """学生批量导入的初始密码：12 位可读随机串（避开易混淆字符）。"""
    import secrets

    alphabet = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(12))


# 密码哈希摘要：导入去重与日志脱敏共用（不存明文）
def fingerprint(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()[:12]
