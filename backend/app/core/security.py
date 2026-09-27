import base64
import hashlib
import hmac
import time
import uuid
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

# 学生轻量凭证有效期（PRD：无账号体系；凭证用于校验本人身份，不能只靠可猜的 UUID）
STUDENT_TOKEN_TTL_S = 60 * 60 * 24 * 30  # 30 天


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(UTC) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _student_token_mac(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def create_student_token(student_id: uuid.UUID, classroom_id: uuid.UUID) -> str:
    """入班时发放的轻量凭证：HMAC 签名，携带学生/课堂/过期时间。"""
    exp = int(time.time()) + STUDENT_TOKEN_TTL_S
    payload = f"{student_id}:{classroom_id}:{exp}"
    raw = f"{payload}:{_student_token_mac(payload)}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_student_token(
    token: str,
) -> tuple[uuid.UUID, uuid.UUID, int]:
    """校验学生凭证，返回 (student_id, classroom_id, exp)。

    签名错误或已过期抛 ValueError（上层映射为 401）。
    """
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = decoded.rsplit(":", 1)
        expected = _student_token_mac(payload)
        if not hmac.compare_digest(expected, sig):
            raise ValueError("bad signature")
        student_id, classroom_id, exp = payload.split(":")
        if int(exp) < int(time.time()):
            raise ValueError("expired")
        return uuid.UUID(student_id), uuid.UUID(classroom_id), int(exp)
    except Exception as exc:  # noqa: BLE001 - 统一转成「凭证无效」
        raise ValueError("invalid student token") from exc


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)
