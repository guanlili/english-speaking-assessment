"""学生入班凭证（access_token）的测试辅助。

join 响应里的 access_token 按 student_id 记录在本进程内，测试仍按
student_id 组装请求（token=...），与前端“每次请求都带凭证”一致。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_TOKENS: dict[str, str] = {}


@contextmanager
def anonymous(client: Any) -> Iterator[Any]:
    """临时摘掉测试默认带的 Authorization 头，模拟未登录/纯学生请求。"""
    auth = client.headers.pop("Authorization", None)
    try:
        yield client
    finally:
        if auth is not None:
            client.headers["Authorization"] = auth


def remember_join(payload: dict[str, Any]) -> dict[str, Any]:
    """记录 join 响应里的凭证并原样返回（测试里可直接 ["id"] 取值）。"""
    token = payload.get("access_token")
    if isinstance(token, str) and token:
        _TOKENS[str(payload["id"])] = token
    return payload


def token_for(student_id: object) -> str:
    return _TOKENS.get(str(student_id), "")


def student_params(student_id: object, **extra: object) -> dict[str, Any]:
    """学生查询参数：student_id + 本人凭证（+ 覆盖项，如 session_id）。"""
    params: dict[str, Any] = {
        "student_id": str(student_id),
        "token": token_for(student_id),
    }
    params.update(extra)
    return params


def student_form(student_id: object, **extra: object) -> dict[str, Any]:
    """学生提交表单字段：student_id + 本人凭证（+ 覆盖项）。"""
    form: dict[str, Any] = {
        "student_id": str(student_id),
        "token": token_for(student_id),
    }
    form.update(extra)
    return form
