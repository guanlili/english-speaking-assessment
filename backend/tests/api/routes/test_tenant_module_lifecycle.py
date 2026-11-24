"""模块授权生命周期（#517 A 部分）：租期 / 试用状态机测试。

口径锁定：
- 状态优先级：disabled（enabled=false）> expired > scheduled > active；
  关闭与过期同时成立时报 disabled，detail 为 module_not_enabled:<key>。
- 403 detail 区分：未购/关闭/待生效 → ``module_not_enabled:<key>``；
  已到期 → ``module_expired:<key>``。
- 开始时间复用 ``effective_at``；长期 = ``expires_at=null``。
- 到期只关门禁，不物理删除业务作答 / 名册数据。
- 跨租户隔离：A 校授权不影响 B 校闸门。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core import security
from app.models import (
    Attempt,
    Classroom,
    PlatformOperator,
    Student,
    Tenant,
    TenantModule,
    User,
)

API = "/api/v1"
VOCAB_BOOKS = f"{API}/vocabulary/books"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _mk_tenant(db: Session, tag: str, status: str = "active") -> Tenant:
    row = Tenant(
        slug=f"life-{tag}-{_uid()}",
        name_zh=f"生命周期测试校 {tag}",
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_user(db: Session, tenant_id: uuid.UUID, role: str, tag: str) -> User:
    user = User(
        email=f"life-{role}-{tag}-{_uid()}@example.com",
        hashed_password="x",
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _mk_classroom(db: Session, tenant_id: uuid.UUID) -> Classroom:
    row = Classroom(
        code=f"LIF{_uid()[:6].upper()}",
        class_size=8,
        tenant_id=tenant_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_student(db: Session, classroom: Classroom, user: User) -> Student:
    row = Student(
        classroom_id=classroom.id,
        display_name="生命周期测试生",
        user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _headers(user: User, tenant_id: uuid.UUID) -> dict[str, str]:
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


def _grant(
    db: Session,
    tenant_id: uuid.UUID,
    key: str = "vocabulary",
    *,
    enabled: bool = True,
    effective_at: datetime | None = None,
    expires_at: datetime | None = None,
    grant_type: str = "manual",
) -> TenantModule:
    row = TenantModule(
        tenant_id=tenant_id,
        module_key=key,
        enabled=enabled,
        effective_at=effective_at,
        expires_at=expires_at,
        grant_type=grant_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _operator(db: Session) -> PlatformOperator | None:
    return db.exec(select(PlatformOperator)).first()


# ── 1. 缺行 = 未购买 ────────────────────────────────────────────────────


def test_missing_row_403_not_enabled(client: TestClient, db: Session) -> None:
    """无授权行：词汇端点 403 module_not_enabled:vocabulary。"""
    tenant = _mk_tenant(db, "missing")
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:vocabulary"


# ── 2. disabled 优先级高于 expired ─────────────────────────────────────


def test_disabled_beats_expired(client: TestClient, db: Session) -> None:
    """enabled=false 且已过期：仍报 module_not_enabled（disabled 优先）。"""
    tenant = _mk_tenant(db, "disabled-expired")
    _grant(
        db,
        tenant.id,
        enabled=False,
        expires_at=datetime.now(UTC) - timedelta(days=2),
    )
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:vocabulary"
    assert resp.json()["detail"] != "module_expired:vocabulary"


# ── 3. 未来开始时间 = 待生效 ────────────────────────────────────────────


def test_scheduled_future_start_403(client: TestClient, db: Session) -> None:
    """effective_at 在未来：未生效，403 module_not_enabled。"""
    tenant = _mk_tenant(db, "scheduled")
    _grant(
        db,
        tenant.id,
        effective_at=datetime.now(UTC) + timedelta(days=7),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:vocabulary"


# ── 4. 已到期 → module_expired ──────────────────────────────────────────


def test_expired_403_module_expired(client: TestClient, db: Session) -> None:
    """enabled=true 且 expires_at 已过：403 module_expired:vocabulary。"""
    tenant = _mk_tenant(db, "expired")
    _grant(
        db,
        tenant.id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_expired:vocabulary"


# ── 5. 长期（expires null）可用 ─────────────────────────────────────────


def test_long_term_enabled_200(client: TestClient, db: Session) -> None:
    """expires_at=null：长期有效，闸门放行。"""
    tenant = _mk_tenant(db, "longterm")
    _grant(db, tenant.id, expires_at=None)
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert resp.status_code == 200, resp.text


# ── 6. trial → paid 续期：状态保持 active，既有数据不重算 ────────────────


def test_trial_to_paid_renewal_stays_active(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "renewal")
    teacher = _mk_user(db, tenant.id, "teacher", "t")

    trial_resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "trial",
            "expires_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert trial_resp.status_code == 200, trial_resp.text
    assert trial_resp.json()["state"] == "active"
    assert trial_resp.json()["grant_type"] == "trial"

    books = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert books.status_code == 200, books.text

    paid_resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "paid",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert paid_resp.status_code == 200, paid_resp.text
    body = paid_resp.json()
    assert body["state"] == "active"
    assert body["grant_type"] == "paid"
    # 开关未被续期改写清空
    assert body["enabled"] is True

    books2 = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert books2.status_code == 200, books2.text

    row = db.exec(
        select(TenantModule).where(TenantModule.tenant_id == tenant.id)  # type: ignore[arg-type]
    ).first()
    assert row is not None
    assert row.grant_type == "paid"
    assert row.enabled is True


# ── 7. 到期后重新开通恢复 ───────────────────────────────────────────────


def test_reopen_after_expiry_restores(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "reopen")
    _grant(db, tenant.id, expires_at=datetime.now(UTC) - timedelta(days=1))
    teacher = _mk_user(db, tenant.id, "teacher", "t")

    blocked = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "module_expired:vocabulary"

    reopen = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "paid",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert reopen.status_code == 200, reopen.text
    assert reopen.json()["state"] == "active"

    restored = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert restored.status_code == 200, restored.text


# ── 8. 跨租户隔离 ───────────────────────────────────────────────────────


def test_cross_tenant_isolation(client: TestClient, db: Session) -> None:
    school_a = _mk_tenant(db, "A")
    school_b = _mk_tenant(db, "B")
    _grant(db, school_a.id)

    teacher_a = _mk_user(db, school_a.id, "teacher", "a")
    teacher_b = _mk_user(db, school_b.id, "teacher", "b")

    resp_a = client.get(VOCAB_BOOKS, headers=_headers(teacher_a, school_a.id))
    assert resp_a.status_code == 200, resp_a.text

    resp_b = client.get(VOCAB_BOOKS, headers=_headers(teacher_b, school_b.id))
    assert resp_b.status_code == 403, resp_b.text
    assert resp_b.json()["detail"] == "module_not_enabled:vocabulary"


# ── 9. 审计前后值完整留痕 ───────────────────────────────────────────────


def test_audit_records_all_before_after_values(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "audit")
    operator = _operator(db)
    assert operator is not None

    first = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "trial",
            "expires_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert first.status_code == 200, first.text

    history = client.get(
        f"{API}/admin/tenants/{tenant.id}/modules/audit",
        headers=operator_token_headers,
    )
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 1
    first_audit = rows[0]
    assert first_audit["enabled_before"] is None
    assert first_audit["enabled_after"] is True
    assert first_audit["effective_at_before"] is None
    assert first_audit["grant_type_before"] is None
    assert first_audit["grant_type_after"] == "trial"
    assert first_audit["expires_at_before"] is None
    assert first_audit["expires_at_after"] is not None
    assert first_audit["granted_by_before"] is None
    assert first_audit["granted_by_after"] == str(operator.id)
    assert first_audit["actor_operator_id"] == str(operator.id)

    second = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "paid",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert second.status_code == 200, second.text

    history2 = client.get(
        f"{API}/admin/tenants/{tenant.id}/modules/audit?module_key=vocabulary",
        headers=operator_token_headers,
    )
    rows2 = history2.json()
    assert len(rows2) == 2
    latest = rows2[0]
    assert latest["enabled_before"] is True
    assert latest["enabled_after"] is True
    assert latest["grant_type_before"] == "trial"
    assert latest["grant_type_after"] == "paid"
    assert latest["expires_at_before"] == first_audit["expires_at_after"]
    assert latest["expires_at_after"] is not None
    assert latest["granted_by_before"] == str(operator.id)
    assert latest["granted_by_after"] == str(operator.id)


# ── 10. expiring_within_days 筛选 ───────────────────────────────────────


def test_expiring_within_days_filter(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    soon = _mk_tenant(db, "soon")  # 3 天后到期 → 命中 7 天窗口
    _grant(
        db,
        soon.id,
        expires_at=datetime.now(UTC) + timedelta(days=3),
        grant_type="trial",
    )
    later = _mk_tenant(db, "later")  # 30 天后 → 不命中
    _grant(
        db,
        later.id,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        grant_type="paid",
    )
    already = _mk_tenant(db, "already")  # 已过期 → 不命中
    _grant(
        db,
        already.id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    longterm = _mk_tenant(db, "longterm")  # 长期 → 不命中
    _grant(db, longterm.id, expires_at=None)

    resp = client.get(
        f"{API}/admin/tenants?expiring_within_days=7",
        headers=operator_token_headers,
    )
    assert resp.status_code == 200, resp.text
    slugs = {row["slug"] for row in resp.json()}
    assert soon.slug in slugs
    assert later.slug not in slugs
    assert already.slug not in slugs
    assert longterm.slug not in slugs


# ── 11. /modules/me statuses 与门禁同口径 + trial days_left ─────────────


def test_modules_me_statuses_match_gate(client: TestClient, db: Session) -> None:
    tenant = _mk_tenant(db, "me-status")
    _grant(
        db,
        tenant.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        grant_type="trial",
    )
    teacher = _mk_user(db, tenant.id, "teacher", "t")

    me = client.get(f"{API}/modules/me", headers=_headers(teacher, tenant.id))
    assert me.status_code == 200, me.text
    payload = me.json()
    assert payload["modules"] == ["vocabulary"]

    statuses = {row["module_key"]: row for row in payload["statuses"]}
    assert set(statuses) == {"speaking", "vocabulary"}

    vocab = statuses["vocabulary"]
    assert vocab["state"] == "active"
    assert vocab["enabled"] is True
    assert vocab["grant_type"] == "trial"
    assert vocab["expires_at"] is not None
    assert isinstance(vocab["days_left"], int)
    assert 1 <= vocab["days_left"] <= 7
    # starts_at 是 effective_at 的镜像
    assert vocab["starts_at"] == vocab["effective_at"]

    speaking = statuses["speaking"]
    assert speaking["state"] == "not_granted"
    assert speaking["enabled"] is False
    assert speaking["expires_at"] is None
    assert speaking["days_left"] is None


# ── 12. 到期后业务数据仍在（无物理删除）─────────────────────────────────


def test_business_data_retained_after_expiry(client: TestClient, db: Session) -> None:
    tenant = _mk_tenant(db, "retain")
    classroom = _mk_classroom(db, tenant.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    student = _mk_student(db, classroom, student_user)

    attempt = Attempt(
        tenant_id=tenant.id,
        item_type="passage",
        item_id=uuid.uuid4(),
        student_id=student.id,
        audio_path="retention-test.webm",
        duration_s=1.0,
        status="done",
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    _grant(db, tenant.id, expires_at=None)
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    before = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert before.status_code == 200, before.text

    # 到期：只改授权行，不触碰业务表
    row = db.exec(
        select(TenantModule).where(TenantModule.tenant_id == tenant.id)  # type: ignore[arg-type]
    ).first()
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    db.add(row)
    db.commit()

    blocked = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "module_expired:vocabulary"

    # 作答 / 名册数据物理留存
    attempt_count = len(
        db.exec(select(Attempt).where(Attempt.tenant_id == tenant.id)).all()  # type: ignore[arg-type]
    )
    student_count = len(
        db.exec(select(Student).where(Student.classroom_id == classroom.id)).all()  # type: ignore[arg-type]
    )
    classroom_count = len(
        db.exec(select(Classroom).where(Classroom.tenant_id == tenant.id)).all()  # type: ignore[arg-type]
    )
    assert attempt_count == 1
    assert student_count == 1
    assert classroom_count == 1


# ── 附加：请求级校验 422 ────────────────────────────────────────────────


def test_validation_trial_requires_expires_at(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "trial-no-expiry")
    resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={"enabled": True, "grant_type": "trial"},
        headers=operator_token_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "trial_requires_expires_at"


def test_validation_invalid_grant_type(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "bad-type")
    resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={"enabled": True, "grant_type": "enterprise"},
        headers=operator_token_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "grant_type_invalid"


def test_validation_expires_before_start(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "exp-before-start")
    resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "paid",
            "effective_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "expires_at_must_be_after_effective_at"


# ── 附加：空开始时间 + 过去到期日不被 422 挡住 ──────────────────────────────


def test_past_expires_without_start_is_expired(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    """无开始时间（立即生效）但到期日已过：允许写入，状态直接 expired。"""
    tenant = _mk_tenant(db, "past-expiry")
    resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "paid",
            "expires_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "expired"
    assert body["enabled"] is True
    assert body["effective_at"] is None
    assert body["starts_at"] is None
    assert body["expires_at"] is not None

    teacher = _mk_user(db, tenant.id, "teacher", "t")
    blocked = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "module_expired:vocabulary"


def test_close_expired_module_not_blocked_by_expiry_check(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    """关闭已过期模块（enabled=false）不被到期日先后校验挡住。"""
    tenant = _mk_tenant(db, "close-exp")
    _grant(db, tenant.id, expires_at=datetime.now(UTC) - timedelta(days=2))
    teacher = _mk_user(db, tenant.id, "teacher", "t")

    blocked = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "module_expired:vocabulary"

    close = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={"enabled": False},
        headers=operator_token_headers,
    )
    assert close.status_code == 200, close.text
    body = close.json()
    assert body["state"] == "disabled"
    assert body["enabled"] is False

    blocked_after = client.get(VOCAB_BOOKS, headers=_headers(teacher, tenant.id))
    assert blocked_after.status_code == 403, blocked_after.text
    assert blocked_after.json()["detail"] == "module_not_enabled:vocabulary"
