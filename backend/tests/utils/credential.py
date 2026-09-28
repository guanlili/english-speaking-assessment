"""测试用学生/教师身份辅助。

账号制：学生 = role=student 的 User（学号登录拿 JWT），课堂请求带
Authorization 头；匿名入班/轻量凭证已退役。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security import get_password_hash
from app.models import Student, User

# 记住本进程内建过的学生账号（学号 → 密码），重复登录不用重建
_student_accounts: dict[str, str] = {}


@contextmanager
def anonymous(client: Any) -> Iterator[Any]:
    """临时摘掉测试默认带的 Authorization 头，模拟未登录/纯学生请求。"""
    auth = client.headers.pop("Authorization", None)
    try:
        yield client
    finally:
        if auth:
            client.headers["Authorization"] = auth


def create_student_user(db: Session, full_name: str = "测试学生") -> User:
    """建一个学生账号（不入班），学号随机、密码进程内记忆。"""
    import uuid

    from tests.utils.utils import random_lower_string

    username = f"stu{uuid.uuid4().hex[:10]}"
    password = random_lower_string()
    user = User(
        username=username,
        full_name=full_name,
        role="student",
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _student_accounts[username] = password
    return user


def login_headers(client: TestClient, username: str) -> dict[str, str]:
    """学号/邮箱登录，返回 Authorization 头。"""
    password = _student_accounts[username]
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def join_as(
    client: TestClient, code: str, user: User, display_name: str | None = None
) -> dict:
    """学生账号登录后入班，返回 {student, headers, user}。"""
    headers = login_headers(client, user.username)  # type: ignore
    body: dict[str, Any] = {"display_name": display_name} if display_name else {}
    resp = client.post(f"/api/v1/classes/{code}/join", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return {"student": resp.json(), "headers": headers, "user": user}


def make_student(
    db: Session, client: TestClient, code: str, name: str = "测试学生"
) -> dict:
    """一步到位：建学生账号 + 登录 + 入班。"""
    user = create_student_user(db, full_name=name)
    return join_as(client, code, user, display_name=name)


def student_db_row(db: Session, student_id: str) -> Student | None:
    return db.get(Student, _uuid(student_id))


def _uuid(value: str) -> Any:
    import uuid

    return uuid.UUID(value)
