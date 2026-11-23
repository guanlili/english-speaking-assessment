"""模块授权（#516 / #517）：整校 × speaking/vocabulary 开关的服务端闸门测试。

口径锁定：
- 缺行 = 未购买（默认关）；存量回填 speaking=on、vocabulary=off；新租户两关。
- 未购统一 403，detail 稳定标识 ``module_not_enabled:<key>``；401 只留给
  token 无效/过期。
- 404 优先于 403：课堂成员不存在/非本班先 404，成员确定后再判模块 403。
- 平台运营的五级字典/统计端点豁免学校模块口径。
- paused 学校由身份门先判 403 Inactive tenant，模块闸门不覆盖该语义。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core import security
from app.models import (
    Classroom,
    Student,
    Tenant,
    TenantModule,
    User,
)

API = "/api/v1"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _mk_tenant(db: Session, tag: str, status: str = "active") -> Tenant:
    row = Tenant(
        slug=f"ent-{tag}-{_uid()}",
        name_zh=f"授权测试校 {tag}",
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_user(db: Session, tenant_id: uuid.UUID, role: str, tag: str) -> User:
    user = User(
        email=f"ent-{role}-{tag}-{_uid()}@example.com",
        hashed_password="x",
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _mk_classroom(
    db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID | None = None
) -> Classroom:
    row = Classroom(
        code=f"ENT{_uid()[:6].upper()}",
        class_size=8,
        owner_id=owner_id,
        tenant_id=tenant_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_student(db: Session, classroom: Classroom, user: User) -> Student:
    row = Student(
        classroom_id=classroom.id,
        display_name="授权测试生",
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
    key: str,
    enabled: bool = True,
    effective_at: datetime | None = None,
) -> TenantModule:
    row = TenantModule(
        tenant_id=tenant_id,
        module_key=key,
        enabled=enabled,
        effective_at=effective_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _module_rows(db: Session, tenant_id: uuid.UUID) -> list[TenantModule]:
    return list(
        db.exec(select(TenantModule).where(TenantModule.tenant_id == tenant_id)).all()
    )


# ── 默认关闭 / 开启放行 ──────────────────────────────────────────────


def test_vocabulary_default_off_403(client: TestClient, db: Session) -> None:
    """无配置租户：教师词库端点 403 module_not_enabled:vocabulary。"""
    tenant = _mk_tenant(db, "off")
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:vocabulary"


def test_vocabulary_enabled_200(client: TestClient, db: Session) -> None:
    tenant = _mk_tenant(db, "on")
    _grant(db, tenant.id, "vocabulary")
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert resp.status_code == 200, resp.text


def test_speaking_default_off_403(client: TestClient, db: Session) -> None:
    """无配置租户：学生口语 today 端点 403 module_not_enabled:speaking。"""
    tenant = _mk_tenant(db, "sp-off")
    classroom = _mk_classroom(db, tenant.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    resp = client.get(
        f"{API}/classes/{classroom.code}/today",
        headers=_headers(student_user, tenant.id),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:speaking"


# ── speaking 侧 404 / 403 优先级（与 vocabulary 同一顺序）───────────────


def test_speaking_404_before_403_for_non_member(
    client: TestClient, db: Session
) -> None:
    """非本班学生 + 未购 speaking：先 404（不泄露课堂存在性），不先抛模块 403。"""
    tenant = _mk_tenant(db, "sp-404-out")
    classroom = _mk_classroom(db, tenant.id)
    outsider = _mk_user(db, tenant.id, "student", "out")
    resp = client.get(
        f"{API}/classes/{classroom.code}/revision",
        headers=_headers(outsider, tenant.id),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Student not found"


def test_speaking_403_after_member_resolution_when_off(
    client: TestClient, db: Session
) -> None:
    """本班学生 + 未购 speaking：成员解析通过后再 403。"""
    tenant = _mk_tenant(db, "sp-403-member")
    classroom = _mk_classroom(db, tenant.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    resp = client.get(
        f"{API}/classes/{classroom.code}/revision",
        headers=_headers(student_user, tenant.id),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:speaking"


def test_speaking_member_enabled_returns_200(client: TestClient, db: Session) -> None:
    """本班学生 + 已购 speaking：200（空课堂修订号也算放行）。"""
    tenant = _mk_tenant(db, "sp-member-on")
    _grant(db, tenant.id, "speaking")
    classroom = _mk_classroom(db, tenant.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    resp = client.get(
        f"{API}/classes/{classroom.code}/revision",
        headers=_headers(student_user, tenant.id),
    )
    assert resp.status_code == 200, resp.text


# ── 单买口径：只买单词 / 只买口语 ─────────────────────────────────────


def test_only_vocabulary_speaking_blocked_baseline_open(
    client: TestClient, db: Session
) -> None:
    """只买 vocabulary：词汇 200、口语 403，班级底座（教师课堂列表）仍 200。"""
    tenant = _mk_tenant(db, "voc-only")
    _grant(db, tenant.id, "vocabulary")
    teacher = _mk_user(db, tenant.id, "teacher", "t")

    vocab = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert vocab.status_code == 200, vocab.text

    baseline = client.get(f"{API}/classes", headers=_headers(teacher, tenant.id))
    assert baseline.status_code == 200, baseline.text

    classroom = _mk_classroom(db, tenant.id, owner_id=teacher.id)
    speaking = client.get(
        f"{API}/classes/{classroom.code}/today",
        headers=_headers(teacher, tenant.id),
    )
    assert speaking.status_code == 403, speaking.text
    assert speaking.json()["detail"] == "module_not_enabled:speaking"


def test_only_speaking_vocabulary_blocked(client: TestClient, db: Session) -> None:
    """只买 speaking：词汇端点 403；口语闸门放行（不再抛模块 403）。"""
    tenant = _mk_tenant(db, "sp-only")
    _grant(db, tenant.id, "speaking")
    teacher = _mk_user(db, tenant.id, "teacher", "t")

    vocab = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert vocab.status_code == 403, vocab.text
    assert vocab.json()["detail"] == "module_not_enabled:vocabulary"

    classroom = _mk_classroom(db, tenant.id, owner_id=teacher.id)
    speaking = client.get(
        f"{API}/classes/{classroom.code}/today",
        headers=_headers(teacher, tenant.id),
    )
    # 口语闸门已放行；后续是业务内容层响应（空题单/404 等），不得是模块 403
    assert speaking.status_code != 403 or "module_not_enabled" not in str(
        speaking.json().get("detail", "")
    ), speaking.text


def test_both_modules_open(client: TestClient, db: Session) -> None:
    tenant = _mk_tenant(db, "both")
    _grant(db, tenant.id, "speaking")
    _grant(db, tenant.id, "vocabulary")
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    vocab = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert vocab.status_code == 200, vocab.text
    me = client.get(f"{API}/modules/me", headers=_headers(teacher, tenant.id))
    assert me.status_code == 200, me.text
    assert set(me.json()["modules"]) == {"speaking", "vocabulary"}


# ── 404 / 403 优先级（vocabulary 课堂成员口径）────────────────────────


def test_404_before_403_for_non_member(client: TestClient, db: Session) -> None:
    """非本班成员 + 未购 vocabulary：先 404（不泄露课堂存在性）。"""
    tenant = _mk_tenant(db, "404-nonmember")
    classroom = _mk_classroom(db, tenant.id)
    outsider = _mk_user(db, tenant.id, "student", "out")
    resp = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/student/books",
        headers=_headers(outsider, tenant.id),
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Student not found"


def test_403_after_member_resolution_when_off(client: TestClient, db: Session) -> None:
    """本班成员 + 未购：成员解析通过后再 403。"""
    tenant = _mk_tenant(db, "403-member")
    classroom = _mk_classroom(db, tenant.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    resp = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/student/books",
        headers=_headers(student_user, tenant.id),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:vocabulary"


def test_member_enabled_returns_200(client: TestClient, db: Session) -> None:
    """本班成员 + 已购：200（空清单也算放行）。"""
    tenant = _mk_tenant(db, "member-on")
    _grant(db, tenant.id, "vocabulary")
    classroom = _mk_classroom(db, tenant.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    resp = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/student/books",
        headers=_headers(student_user, tenant.id),
    )
    assert resp.status_code == 200, resp.text


# ── 生效时间 / paused / 运营豁免 ──────────────────────────────────────


def test_future_effective_at_not_active(client: TestClient, db: Session) -> None:
    """effective_at 在未来：授权尚未生效，按未购买 403。"""
    tenant = _mk_tenant(db, "future")
    future = datetime.now(UTC) + timedelta(days=7)
    _grant(db, tenant.id, "vocabulary", effective_at=future)
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "module_not_enabled:vocabulary"


def test_paused_tenant_blocked_by_identity_gate(
    client: TestClient, db: Session
) -> None:
    """paused 学校：身份门先判 Inactive tenant，模块闸门不覆盖该 403 语义。"""
    tenant = _mk_tenant(db, "paused", status="paused")
    _grant(db, tenant.id, "vocabulary")
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(f"{API}/vocabulary/books", headers=_headers(teacher, tenant.id))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Inactive tenant"


def test_operator_level_stats_exempt(
    client: TestClient,
    operator_token_headers: dict[str, str],
) -> None:
    """平台运营的五级字典统计端点：不走学校模块口径，照常 200。"""
    resp = client.get(
        f"{API}/admin/vocab-levels/stats",
        headers=operator_token_headers,
    )
    assert resp.status_code == 200, resp.text


# ── 运营后台改写 + 审计留痕 ──────────────────────────────────────────


def test_admin_toggle_writes_audit(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    """运营开启 vocabulary → 审计落 before=None/after=true；再关闭留前后值。"""
    tenant = _mk_tenant(db, "audit")

    on = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={"enabled": True},
        headers=operator_token_headers,
    )
    assert on.status_code == 200, on.text
    assert on.json()["enabled"] is True

    history = client.get(
        f"{API}/admin/tenants/{tenant.id}/modules/audit",
        headers=operator_token_headers,
    )
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 1
    assert rows[0]["module_key"] == "vocabulary"
    assert rows[0]["enabled_before"] is None
    assert rows[0]["enabled_after"] is True
    assert rows[0]["actor_operator_id"] is not None

    off = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={"enabled": False},
        headers=operator_token_headers,
    )
    assert off.status_code == 200, off.text

    history2 = client.get(
        f"{API}/admin/tenants/{tenant.id}/modules/audit?module_key=vocabulary",
        headers=operator_token_headers,
    )
    rows2 = history2.json()
    assert len(rows2) == 2
    latest = rows2[0]
    assert latest["enabled_before"] is True
    assert latest["enabled_after"] is False


def test_admin_toggle_unknown_module_422(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    tenant = _mk_tenant(db, "badkey")
    resp = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/whiteboard",
        json={"enabled": True},
        headers=operator_token_headers,
    )
    assert resp.status_code == 422, resp.text


def test_modules_me_empty_for_unconfigured(client: TestClient, db: Session) -> None:
    tenant = _mk_tenant(db, "me-empty")
    teacher = _mk_user(db, tenant.id, "teacher", "t")
    resp = client.get(f"{API}/modules/me", headers=_headers(teacher, tenant.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["modules"] == []
    assert _module_rows(db, tenant.id) == []
