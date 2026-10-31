"""多租户 B2：登录租户解析 + 学校入口 + 两校同号双登录（V1.0 AC-01）."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.security import get_password_hash
from app.models import Tenant, User

PWD = "Passw0rd!123"


def _make_tenant(db: Session, name: str) -> Tenant:
    t = Tenant(slug=f"{name}-{uuid.uuid4().hex[:6]}", name_zh=f"{name} 校")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_student(db: Session, tenant: Tenant, username: str) -> User:
    u = User(
        hashed_password=get_password_hash(PWD),
        username=username,
        role="student",
        tenant_id=tenant.id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_school_login_info_endpoint(client: TestClient, db: Session) -> None:
    """公开学校解析：已知 slug 回名称；未知/停用统一 404 不泄露差异。"""
    ok = client.get("/api/v1/login/school/default")
    assert ok.status_code == 200
    body = ok.json()
    assert body["slug"] == "default"
    assert "name_zh" in body
    assert "用户" not in str(body)  # 受限读取：不含任何账号信息

    assert client.get("/api/v1/login/school/no-such").status_code == 404

    t = _make_tenant(db, "停用")
    t.status = "suspended"
    db.add(t)
    db.commit()
    assert client.get(f"/api/v1/login/school/{t.slug}").status_code == 404


def test_same_username_two_tenants_both_login(client: TestClient, db: Session) -> None:
    """AC-01 核心：两校同号各自经学校入口登录互不影响。"""
    ta = _make_tenant(db, "甲")
    tb = _make_tenant(db, "乙")
    sid = f"s{uuid.uuid4().hex[:8]}"
    ua = _make_student(db, ta, sid)
    ub = _make_student(db, tb, sid)
    assert ua.id != ub.id  # 复合唯一下的两个独立账号

    def login(school: str | None):
        data = {"username": sid, "password": PWD}
        params = {"school": school} if school else {}
        return client.post("/api/v1/login/access-token", data=data, params=params)

    ra = login(ta.slug)
    rb = login(tb.slug)
    assert ra.status_code == 200
    assert rb.status_code == 200

    me_a = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {ra.json()['access_token']}"},
    )
    me_b = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {rb.json()['access_token']}"},
    )
    assert me_a.json()["id"] == str(ua.id)
    assert me_b.json()["id"] == str(ub.id)


def test_wrong_school_rejected_without_leak(client: TestClient, db: Session) -> None:
    """错校登录与密码错误同文案 400——不泄露账号属于哪校（AC-01/03）。"""
    ta = _make_tenant(db, "丙")
    sid = f"s{uuid.uuid4().hex[:8]}"
    _make_student(db, ta, sid)

    r_wrong_school = client.post(
        "/api/v1/login/access-token",
        data={"username": sid, "password": PWD},
        params={"school": "another-school"},
    )
    r_wrong_pwd = client.post(
        "/api/v1/login/access-token",
        data={"username": sid, "password": "wrong"},
        params={"school": ta.slug},
    )
    r_unknown_school = client.post(
        "/api/v1/login/access-token",
        data={"username": sid, "password": PWD},
        params={"school": "no-such-school"},
    )
    assert r_wrong_school.status_code == 400
    assert r_wrong_pwd.status_code == 400
    assert r_unknown_school.status_code == 400
    details = {
        r_wrong_school.json()["detail"],
        r_wrong_pwd.json()["detail"],
        r_unknown_school.json()["detail"],
    }
    assert len(details) == 1  # 三种失败同一文案


def test_token_carries_tenant_id(client: TestClient, db: Session) -> None:
    """JWT 带 tid 声明（B2）；旧入口（不带学校）同样带。"""
    import base64
    import json

    ta = _make_tenant(db, "丁")
    sid = f"s{uuid.uuid4().hex[:8]}"
    _make_student(db, ta, sid)
    r = client.post(
        "/api/v1/login/access-token",
        data={"username": sid, "password": PWD},
        params={"school": ta.slug},
    )
    assert r.status_code == 200
    payload = r.json()["access_token"].split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.b64decode(payload))
    assert claims["tid"] == str(ta.id)


def test_global_login_no_school_returns_first(client: TestClient, db: Session) -> None:
    """不带学校的全局查找命中重号 → 返回 first()（单校窗口行为）。

    多租户上线后旧入口仅限单校窗口，跨校账号走学校入口。
    """
    ta = _make_tenant(db, "戊")
    sid = f"s{uuid.uuid4().hex[:8]}"
    _make_student(db, ta, sid)
    r = client.post(
        "/api/v1/login/access-token",
        data={"username": sid, "password": PWD},
    )
    assert r.status_code == 200
