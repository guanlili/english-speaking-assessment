"""登录限流分桶：学校维度隔离、NAT 出口不连坐、全局兜底仍在（AC-01/AC-08）."""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.routes import login as login_route
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import get_password_hash
from app.models import Tenant, User

PWD = "Passw0rd!123"


def _tenant(db: Session, name: str) -> Tenant:
    t = Tenant(slug=f"{name}-{uuid.uuid4().hex[:6]}", name_zh=f"{name} 校")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _user(db: Session, tenant: Tenant, username: str, role: str = "student") -> User:
    u = User(
        hashed_password=get_password_hash(PWD),
        username=username,
        role=role,
        tenant_id=tenant.id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client: TestClient, school: str | None, username: str, password: str):
    data = {"username": username, "password": password}
    params = {"school": school} if school else {}
    return client.post("/api/v1/login/access-token", data=data, params=params)


def test_limiter_per_bucket_limit_override() -> None:
    """同一张限流表可按桶给不同额度（共享出口桶要比账号桶宽）。"""
    limiter = SlidingWindowLimiter(limit=10, window_s=300)
    for _ in range(3):
        limiter.check("tight", limit=3)
    assert len(limiter._attempts["tight"]) == 3
    limiter.check("wide", limit=5)  # 另一个桶按自己的额度走
    try:
        limiter.check("tight", limit=3)
        raise AssertionError("应抛 429")
    except AssertionError:
        raise
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 429


def test_same_username_two_schools_have_separate_failure_budget(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """AC-01：两校同名学号各自算失败次数，一校被锁不影响另一校登录。"""
    monkeypatch.setattr(login_route, "LOGIN_ACCOUNT_LIMIT", 2)
    ta, tb = _tenant(db, "甲"), _tenant(db, "乙")
    sid = f"s{uuid.uuid4().hex[:8]}"
    _user(db, ta, sid)
    _user(db, tb, sid)

    # 甲校连试两次错密码 → 第三次进 429
    assert _login(client, ta.slug, sid, "wrong").status_code == 400
    assert _login(client, ta.slug, sid, "wrong").status_code == 400
    assert _login(client, ta.slug, sid, "wrong").status_code == 429

    # 乙校同名学号此时仍能正常登录（失败预算互不相干）
    ok = _login(client, tb.slug, sid, PWD)
    assert ok.status_code == 200, ok.text


def test_same_school_egress_not_punished_by_other_students(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """AC-08：同校同出口的失败额度按「一个班」给，不按「一个人」给。"""
    monkeypatch.setattr(login_route, "LOGIN_ACCOUNT_LIMIT", 1)
    monkeypatch.setattr(login_route, "LOGIN_SCHOOL_IP_LIMIT", 5)
    t = _tenant(db, "丙")
    students = [f"s{uuid.uuid4().hex[:8]}" for _ in range(6)]
    for s in students:
        _user(db, t, s)

    # 5 个不同学生各输错一次：都在 400（账号桶每人 1 次，还没超）
    for s in students[:5]:
        assert _login(client, t.slug, s, "wrong").status_code == 400
    # 第 6 个学生即使密码正确，也被同出口桶挡下——证明这个桶真的按出口计数
    assert _login(client, t.slug, students[5], PWD).status_code == 429


def test_global_egress_backstop_still_blocks_cross_school_spray(
    client: TestClient, db: Session, monkeypatch
) -> None:
    """跨校喷洒仍会被全局出口桶兜住（放宽不等同于放开）。"""
    monkeypatch.setattr(login_route, "LOGIN_ACCOUNT_LIMIT", 5)
    monkeypatch.setattr(login_route, "LOGIN_SCHOOL_IP_LIMIT", 5)
    monkeypatch.setattr(login_route, "LOGIN_IP_GLOBAL_LIMIT", 3)
    ta, tb = _tenant(db, "丁"), _tenant(db, "戊")
    _user(db, ta, "a1")
    _user(db, tb, "b1")

    assert _login(client, ta.slug, "a1", "wrong").status_code == 400
    assert _login(client, tb.slug, "b1", "wrong").status_code == 400
    assert _login(client, ta.slug, "a1", "wrong").status_code == 400
    # 换学校、换账号都不行：全局桶已满
    assert _login(client, tb.slug, "b1", PWD).status_code == 429
