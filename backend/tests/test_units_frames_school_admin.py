"""四角色纠偏：单元/句型库归学校管理员（V1.0 §3.2 管理本校题库）.

- 运营 token：读写一律 401（身份分离——C4a 曾误归运营，纠偏回学校侧）
- 校级管理员：CRUD 全通（学校会话+RLS 本校）
- 教师：读（选题用）通、写 403
- 学生：读 403
"""

from fastapi.testclient import TestClient

from app.core.config import settings

API = settings.API_V1_STR


def test_operator_blocked_on_units_and_frames(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    assert (
        client.get(f"{API}/admin/units", headers=operator_token_headers).status_code
        == 401
    )
    assert (
        client.post(
            f"{API}/admin/units",
            json={"order_index": 99, "title": "运营建单元", "topic": "X"},
            headers=operator_token_headers,
        ).status_code
        == 401
    )
    assert (
        client.get(
            f"{API}/admin/sentence-frames", headers=operator_token_headers
        ).status_code
        == 401
    )


def test_school_admin_full_crud(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """校级管理员（首种子账号 role=school_admin）：建/改/删单元全通。"""
    resp = client.post(
        f"{API}/admin/units",
        json={"order_index": 91, "title": "纠偏测试单元", "topic": "Fix"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    uid = resp.json()["id"]
    upd = client.put(
        f"{API}/admin/units/{uid}",
        json={"title": "纠偏改名"},
        headers=superuser_token_headers,
    )
    assert upd.status_code == 200
    assert (
        client.delete(
            f"{API}/admin/units/{uid}", headers=superuser_token_headers
        ).status_code
        == 200
    )


def test_teacher_reads_but_cannot_write(client: TestClient, db) -> None:
    from datetime import timedelta

    from sqlmodel import Session as SAS

    from app.core import security
    from app.core.db import engine
    from app.models import User
    from tests.utils.utils import random_email, random_lower_string

    email, pwd = random_email(), random_lower_string()
    u = User(
        email=email,
        hashed_password=security.get_password_hash(pwd),
        role="teacher",
    )
    with SAS(engine) as s:
        s.add(u)
        s.commit()
        token = security.create_access_token(
            u.id,
            timedelta(minutes=5),
            role="teacher",
            password_hash=u.hashed_password,
        )
    headers = {"Authorization": f"Bearer {token}"}
    try:
        assert (
            client.get(f"{API}/admin/units", headers=headers).status_code == 200
        )  # 选题要读
        assert client.get(f"{API}/admin/topics", headers=headers).status_code == 200
        assert (
            client.post(
                f"{API}/admin/units",
                json={"order_index": 1, "title": "教师建单元", "topic": "T"},
                headers=headers,
            ).status_code
            == 403
        )
    finally:
        with SAS(engine) as s:
            row = s.exec(
                __import__("sqlmodel").select(User).where(User.email == email)
            ).first()
            if row:
                s.delete(row)
                s.commit()
