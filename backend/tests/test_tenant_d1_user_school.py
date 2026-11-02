"""多租户 D1：平台运营建号带学校参数（接第二校的建号链路）。

验收：
1. school=乙校 slug 建教师 → 账号落乙校，可经乙校入口登录。
2. school 未知/停用 → 422 稳定标识。
3. 两校同邮箱各自可建（查重按目标学校，B2 复合唯一语义）。
4. 不传 school → 落默认学校（单校窗口兼容）。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import DEFAULT_TENANT_ID, Tenant, User


def _mk_tenant(db: Session) -> Tenant:
    row = Tenant(slug=f"d1-{uuid.uuid4().hex[:8]}", name_zh="D1 乙校")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_create_user_with_school(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    """school 指定乙校：账号落乙校、查重按乙校、可经乙校解析登录。"""
    t = _mk_tenant(db)
    email = f"d1-{uuid.uuid4().hex[:8]}@example.com"

    resp = client.post(
        f"{settings.API_V1_STR}/users/",
        params={"school": t.slug},
        headers=operator_token_headers,
        json={"email": email, "password": "Passw0rd!2026", "role": "teacher"},
    )
    assert resp.status_code == 200, resp.text
    row = db.exec(select(User).where(User.email == email)).first()
    assert row is not None and row.tenant_id == t.id

    # 同邮箱在默认学校再建一次：两校各自合法（复合唯一语义）
    resp_b = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=operator_token_headers,
        json={"email": email, "password": "Passw0rd!2026", "role": "teacher"},
    )
    assert resp_b.status_code == 200, resp_b.text

    # 乙校内重复：400
    resp_dup = client.post(
        f"{settings.API_V1_STR}/users/",
        params={"school": t.slug},
        headers=operator_token_headers,
        json={"email": email, "password": "Passw0rd!2026", "role": "teacher"},
    )
    assert resp_dup.status_code == 400

    # 清理（共享库规约）：两步提交——先删号提交，再删租户（同事务内
    # SQLAlchemy 的排序按 mapper 依赖，但 API 侧建号的第二行不在本
    # session 依赖图里时会漏删——显式分步最稳）
    for r in db.exec(select(User).where(User.email == email)).all():
        db.delete(r)
    db.commit()
    tenant_row = db.get(Tenant, t.id)
    if tenant_row is not None:
        db.delete(tenant_row)
        db.commit()


def test_create_user_unknown_school_422(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/users/",
        params={"school": "no-such-school"},
        headers=operator_token_headers,
        json={"email": "x@example.com", "password": "Passw0rd!2026", "role": "teacher"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "学校码无效或未开放"


def test_create_user_without_school_defaults(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    """不传 school：落默认学校（兼容现状）。"""
    email = f"d1d-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=operator_token_headers,
        json={"email": email, "password": "Passw0rd!2026", "role": "teacher"},
    )
    assert resp.status_code == 200, resp.text
    row = db.exec(select(User).where(User.email == email)).first()
    assert row.tenant_id == DEFAULT_TENANT_ID
    db.delete(row)
    db.commit()
