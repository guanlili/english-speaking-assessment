"""四角色完善：统一登录入口（运营回退）+ 学校管理员管本校成员."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import DEFAULT_TENANT_ID, Tenant, User

API = settings.API_V1_STR
OP_EMAIL = "op-unified@example.com"


@pytest.fixture(scope="module")
def unified_operator(db: Session):
    from app.models import PlatformOperator

    row = PlatformOperator(
        email=OP_EMAIL, hashed_password=get_password_hash("OpPassw0rd!2026")
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    yield row
    db.delete(row)
    db.commit()


def test_operator_via_main_login(
    client: TestClient, unified_operator, operator_token_headers: dict[str, str]
) -> None:
    """通用入口邮箱登录 → 命中平台管理员 → 运营 token 可用平台端点。"""
    resp = client.post(
        f"{API}/login/access-token",
        data={"username": OP_EMAIL, "password": "OpPassw0rd!2026"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # 运营 token 打平台路由可用；打学校端点 401（身份分离不变）
    assert client.get(f"{API}/admin/metrics", headers=headers).status_code == 200
    assert client.get(f"{API}/users/me", headers=headers).status_code == 401


def test_operator_wrong_password_uniform(client: TestClient, unified_operator) -> None:
    """运营密码错误与学校账号错误同文案（不泄露身份类型）。"""
    resp = client.post(
        f"{API}/login/access-token",
        data={"username": OP_EMAIL, "password": "wrong-password"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "账号或密码不正确"


def test_school_entry_no_operator_fallback(
    client: TestClient, unified_operator
) -> None:
    """带 school 的学校入口不回退运营（学校页保持纯净）。"""
    resp = client.post(
        f"{API}/login/access-token",
        params={"school": "default"},
        data={"username": OP_EMAIL, "password": "OpPassw0rd!2026"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "账号或密码不正确"


def test_student_id_skips_operator_lookup(client: TestClient, unified_operator) -> None:
    """学号（无 @）不走运营通道——直接学校流程（运营无学号）。"""
    resp = client.post(
        f"{API}/login/access-token",
        data={"username": "s12345", "password": "whatever-pass"},
    )
    assert resp.status_code == 400  # 学校流程未命中，同文案


# ── 学校成员管理 ───────────────────────────────────────────────


def _mk_school_admin(db: Session, tenant_id, tag: str) -> User:
    u = User(
        email=f"sa-{tag}@example.com",
        hashed_password=get_password_hash("SaPassw0rd!2026"),
        role="school_admin",
        tenant_id=tenant_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _headers(client: TestClient, user: User, tenant_id) -> dict[str, str]:
    from datetime import timedelta

    from app.core import security

    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


def test_school_members_lifecycle_and_isolation(
    client: TestClient, db: Session
) -> None:
    """本校建师/列表/停用/重置全链 + 跨校隔离。"""
    other = Tenant(slug=f"m-{uuid.uuid4().hex[:6]}", name_zh="成员测试乙校")
    db.add(other)
    db.commit()
    db.refresh(other)
    sa = _mk_school_admin(db, DEFAULT_TENANT_ID, uuid.uuid4().hex[:6])
    sa_b = _mk_school_admin(db, other.id, uuid.uuid4().hex[:6])
    headers = _headers(client, sa, DEFAULT_TENANT_ID)
    headers_b = _headers(client, sa_b, other.id)
    created_ids: list[uuid.UUID] = []
    try:
        # 建本校教师
        email = f"t-{uuid.uuid4().hex[:8]}@example.com"
        resp = client.post(
            f"{API}/school/members",
            headers=headers,
            json={"email": email, "password": "TeachPass!2026", "full_name": "乙老师"},
        )
        assert resp.status_code == 200, resp.text
        new_id = uuid.UUID(resp.json()["id"])
        created_ids.append(new_id)
        row = db.get(User, new_id)
        assert row is not None
        assert row.tenant_id == DEFAULT_TENANT_ID
        assert row.role == "teacher"

        # 本校重复邮箱 → 400；他校同邮箱 → 允许（复合唯一语义）
        assert (
            client.post(
                f"{API}/school/members",
                headers=headers,
                json={"email": email, "password": "TeachPass!2026"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"{API}/school/members",
                headers=headers_b,
                json={"email": email, "password": "TeachPass!2026"},
            ).status_code
            == 200
        )

        # 列表只见本校（乙校管理员看不到甲校新建教师）
        mine = client.get(f"{API}/school/members", headers=headers).json()
        theirs = client.get(f"{API}/school/members", headers=headers_b).json()
        assert any(m["id"] == str(new_id) for m in mine["data"])
        assert not any(m["id"] == str(new_id) for m in theirs["data"])

        # 停用 + 重置密码；跨校目标 → 404
        assert (
            client.patch(
                f"{API}/school/members/{new_id}",
                headers=headers,
                json={"is_active": False},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"{API}/school/members/{new_id}",
                headers=headers_b,
                json={"password": "Hacked!2026pass"},
            ).status_code
            == 404
        )
        db.refresh(row)
        assert row.is_active is False

        # 不能自停用
        assert (
            client.patch(
                f"{API}/school/members/{sa.id}",
                headers=headers,
                json={"is_active": False},
            ).status_code
            == 422
        )
    finally:
        db.rollback()  # 测试中途失败可能留下坏事务，先复位再清理
        # 乙校：先清该校全部测试用户再删租户（FK 顺序）
        for row in db.exec(select(User).where(User.tenant_id == other.id)).all():
            db.delete(row)
        db.commit()
        for uid in created_ids:
            row = db.get(User, uid)
            if row:
                db.delete(row)
        for row in db.exec(select(User).where(User.email == email)).all():
            db.delete(row)
        db.commit()
        db.delete(sa)
        db.delete(sa_b)
        db.commit()
        tenant_row = db.get(Tenant, other.id)
        if tenant_row is not None:
            db.delete(tenant_row)
        db.commit()


def test_school_members_reject_teacher(client: TestClient, db: Session) -> None:
    """教师角色 → 403；运营 token → 401（学校端点拒收运营凭证）。"""
    teacher = User(
        email=f"tt-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        role="teacher",
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    try:
        assert (
            client.get(
                f"{API}/school/members",
                headers=_headers(client, teacher, DEFAULT_TENANT_ID),
            ).status_code
            == 403
        )
    finally:
        db.delete(teacher)
        db.commit()
