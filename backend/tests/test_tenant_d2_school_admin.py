"""多租户 D2：平台运营的学校管理 + 用户管理学校维度.

验收：
1. 学校 CRUD：运营可列表/开校/停用；学校侧账号与匿名一律拒。
2. 开校即可用：新学校立即出现在入口解析、运营建号可用其 slug。
3. 停用即挡新登录：入口 404 + 直连认证失败（第二道防线）；
   默认学校不可停用；停用可恢复。
4. 用户列表学校过滤 + 响应带 tenant_id（运营区分账号归属）。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import DEFAULT_TENANT_ID, Tenant, User

API = settings.API_V1_STR


def _cleanup_tenant(db: Session, slug: str) -> None:
    row = db.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if row is None:
        return
    users = db.exec(select(User).where(User.tenant_id == row.id)).all()
    for u in users:
        db.delete(u)
    db.commit()
    db.delete(row)
    db.commit()


def test_tenant_crud_operator_only(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    slug = f"d2-{uuid.uuid4().hex[:8]}"
    try:
        # 开校
        resp = client.post(
            f"{API}/admin/tenants",
            headers=operator_token_headers,
            json={"slug": slug, "name_zh": "D2 测试校"},
        )
        assert resp.status_code == 200, resp.text
        tid = resp.json()["id"]
        assert resp.json()["user_count"] == 0

        # 重复 slug → 409
        assert (
            client.post(
                f"{API}/admin/tenants",
                headers=operator_token_headers,
                json={"slug": slug, "name_zh": "重复"},
            ).status_code
            == 409
        )

        # 列表可见 + 计数
        listing = client.get(f"{API}/admin/tenants", headers=operator_token_headers)
        assert listing.status_code == 200
        rows = {r["slug"]: r for r in listing.json()}
        assert slug in rows and "default" in rows

        # 改名 + 停用 + 恢复
        assert (
            client.patch(
                f"{API}/admin/tenants/{tid}",
                headers=operator_token_headers,
                json={"name_zh": "改名后", "status": "paused"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"{API}/admin/tenants/{tid}",
                headers=operator_token_headers,
                json={"status": "active"},
            ).status_code
            == 200
        )
    finally:
        _cleanup_tenant(db, slug)


def test_tenant_endpoints_reject_non_operator(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """学校侧管理员/匿名不得碰学校管理面。"""
    assert (
        client.get(f"{API}/admin/tenants", headers=superuser_token_headers).status_code
        == 401
    )
    assert client.get(f"{API}/admin/tenants").status_code == 401


def test_default_tenant_cannot_pause(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    resp = client.patch(
        f"{API}/admin/tenants/{DEFAULT_TENANT_ID}",
        headers=operator_token_headers,
        json={"status": "paused"},
    )
    assert resp.status_code == 422


def test_pause_blocks_new_logins(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    """停用即挡新登录：入口 404 + 直连认证失败（第二道防线）。"""
    from app import crud
    from app.core.security import get_password_hash

    slug = f"d2p-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(slug=slug, name_zh="停用测试校")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    email = f"d2p-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        User(
            email=email,
            hashed_password=get_password_hash("Passw0rd!2026"),
            role="teacher",
            tenant_id=tenant.id,
        )
    )
    db.commit()
    try:
        # 激活态：入口可见 + 认证成功
        assert client.get(f"{API}/login/school/{slug}").status_code == 200
        assert (
            crud.authenticate(
                session=db, account=email, password="Passw0rd!2026", school_slug=slug
            )
            is not None
        )
        # 停用：入口 404 + 认证失败
        paused = client.patch(
            f"{API}/admin/tenants/{tenant.id}",
            headers=operator_token_headers,
            json={"status": "paused"},
        )
        assert paused.status_code == 200, paused.text
        # API 会话已提交；本测试会话 identity map 里还是停用前的对象，强制过期
        db.expire_all()
        assert client.get(f"{API}/login/school/{slug}").status_code == 404
        assert (
            crud.authenticate(
                session=db, account=email, password="Passw0rd!2026", school_slug=slug
            )
            is None
        )
    finally:
        _cleanup_tenant(db, slug)


def test_users_list_school_filter(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    slug = f"d2f-{uuid.uuid4().hex[:8]}"
    tenant = Tenant(slug=slug, name_zh="过滤测试校")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    email = f"d2f-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        User(
            email=email,
            hashed_password="x",
            role="teacher",
            tenant_id=tenant.id,
        )
    )
    db.commit()
    try:
        resp = client.get(
            f"{API}/users/",
            params={"school": slug},
            headers=operator_token_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["data"][0]["email"] == email
        assert body["data"][0]["tenant_id"] == str(tenant.id)
        # 未知学校码 → 422
        assert (
            client.get(
                f"{API}/users/",
                params={"school": "nope-nope"},
                headers=operator_token_headers,
            ).status_code
            == 422
        )
    finally:
        _cleanup_tenant(db, slug)
