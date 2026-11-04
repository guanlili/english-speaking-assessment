"""多租户 C5b：taxonomy/scenario 跨校写越权收口（issue #310，P1 同类漏网）。

漏洞（已实测复现，本地 RLS 未激活形态）：
- admin_taxonomy.py 的 unit/frame 管理端点只 `session.get(Model, id)` + 404，
  未做租户归属校验——乙校 school_admin 可
  PUT/DELETE /admin/units/{default校unit}、/admin/sentence-frames/{default校frame}
  返回 200，跨校改写/删除他校单元与句型。
- admin_scenarios.py 的加题/批量录入/AI 起草端点只检查 scenario 存在，
  未校验归属——乙校 teacher 可跨校给 default scenario 加题/录入/起草。
- class_frames.py 的学生收藏句型端点未校验 frame 归属——乙校 student 可
  收藏 default 句型。

修复语义（与 PR #308 copy 收口同口径）：跨校源一律 404（按不存在处理，
不泄露存在性），补 content_access.require_same_tenant 守卫。本测试在
无 RLS 的测试环境锁住同一语义，并验证同校写操作不受影响。
"""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.core.tenant_context import tenant_scope
from app.models import (
    DEFAULT_TENANT_ID,
    Classroom,
    SentenceFrame,
    Student,
    Tenant,
    Unit,
    User,
)


def _uid() -> str:
    """用例级唯一标识：module 级共享测试库，重跑/顺序不能撞唯一键。"""
    return uuid.uuid4().hex[:8]


def _mk_user(db: Session, tenant_id, role: str, name: str) -> User:
    user = User(
        email=f"taxc5b-{role}-{name}-{_uid()}@example.com",
        hashed_password="x",
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _token(user: User, tenant_id) -> dict[str, str]:
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def b_tenant(db: Session) -> Tenant:
    row = Tenant(slug=f"taxc5b-{_uid()}", name_zh="taxonomy 越权乙校")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def sa_b(db: Session, b_tenant: Tenant) -> User:
    return _mk_user(db, b_tenant.id, "school_admin", "sa")


@pytest.fixture(scope="module")
def teacher_b(db: Session, b_tenant: Tenant) -> User:
    return _mk_user(db, b_tenant.id, "teacher", "t")


@pytest.fixture(scope="module")
def student_b(db: Session, b_tenant: Tenant) -> User:
    return _mk_user(db, b_tenant.id, "student", "st")


@pytest.fixture(scope="module")
def classroom_b(db: Session, b_tenant: Tenant, student_b: User) -> Classroom:
    with tenant_scope(b_tenant.id):
        cls = Classroom(code=f"TX{_uid()[:6].upper()}", name="乙校课堂")
        db.add(cls)
        db.flush()
        student = Student(
            classroom_id=cls.id, user_id=student_b.id, display_name="乙校生"
        )
        db.add(student)
        db.commit()
        db.refresh(cls)
    return cls


@pytest.fixture(scope="module")
def default_unit(db: Session) -> Unit:
    with tenant_scope(DEFAULT_TENANT_ID):
        row = Unit(title=f"甲单元-{_uid()}", topic="A")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@pytest.fixture(scope="module")
def b_unit(db: Session, b_tenant: Tenant) -> Unit:
    with tenant_scope(b_tenant.id):
        row = Unit(title=f"乙单元-{_uid()}", topic="B")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@pytest.fixture(scope="module")
def default_frame(db: Session) -> SentenceFrame:
    with tenant_scope(DEFAULT_TENANT_ID):
        row = SentenceFrame(
            level="ACADEMIC", purpose="compare", text_en="Compared...", text_zh="比较"
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@pytest.fixture(scope="module")
def b_frame(db: Session, b_tenant: Tenant) -> SentenceFrame:
    with tenant_scope(b_tenant.id):
        row = SentenceFrame(
            level="ACADEMIC", purpose="compare", text_en="乙句...", text_zh="乙句"
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@pytest.fixture(scope="module")
def default_scenario(db: Session) -> Any:
    from app.models import Scenario

    with tenant_scope(DEFAULT_TENANT_ID):
        row = Scenario(topic=f"甲主题-{_uid()}")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# ── 跨校写越权：应 404 ─────────────────────────────────────


def test_cross_school_update_unit_404(
    client: TestClient, sa_b: User, b_tenant: Tenant, default_unit: Unit
) -> None:
    resp = client.put(
        f"/api/v1/admin/units/{default_unit.id}",
        headers=_token(sa_b, b_tenant.id),
        json={"title": "HACKED"},
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_delete_unit_404(
    client: TestClient, sa_b: User, b_tenant: Tenant, default_unit: Unit
) -> None:
    resp = client.delete(
        f"/api/v1/admin/units/{default_unit.id}",
        headers=_token(sa_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_update_frame_404(
    client: TestClient, sa_b: User, b_tenant: Tenant, default_frame: SentenceFrame
) -> None:
    resp = client.put(
        f"/api/v1/admin/sentence-frames/{default_frame.id}",
        headers=_token(sa_b, b_tenant.id),
        json={"status": "archived"},
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_delete_frame_404(
    client: TestClient, sa_b: User, b_tenant: Tenant, default_frame: SentenceFrame
) -> None:
    resp = client.delete(
        f"/api/v1/admin/sentence-frames/{default_frame.id}",
        headers=_token(sa_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_add_question_404(
    client: TestClient,
    teacher_b: User,
    b_tenant: Tenant,
    default_scenario: Any,
) -> None:
    resp = client.post(
        f"/api/v1/admin/scenarios/{default_scenario.id}/questions",
        headers=_token(teacher_b, b_tenant.id),
        json={"text": "HACKED question"},
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_batch_questions_404(
    client: TestClient,
    teacher_b: User,
    b_tenant: Tenant,
    default_scenario: Any,
) -> None:
    resp = client.post(
        f"/api/v1/admin/scenarios/{default_scenario.id}/questions/batch",
        headers=_token(teacher_b, b_tenant.id),
        json={"items": [{"text": "HACKED item"}]},
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_generate_404(
    client: TestClient,
    teacher_b: User,
    b_tenant: Tenant,
    default_scenario: Any,
) -> None:
    resp = client.post(
        f"/api/v1/admin/scenarios/{default_scenario.id}/questions/generate",
        headers=_token(teacher_b, b_tenant.id),
        json={"band": "B1", "count": 2, "hint": "hi"},
    )
    assert resp.status_code == 404, resp.text


def test_cross_school_student_favorite_frame_404(
    client: TestClient,
    student_b: User,
    b_tenant: Tenant,
    classroom_b: Classroom,
    default_frame: SentenceFrame,
) -> None:
    resp = client.post(
        f"/api/v1/classes/{classroom_b.code}/frame-favorites",
        headers=_token(student_b, b_tenant.id),
        json={"frame_id": str(default_frame.id)},
    )
    assert resp.status_code == 404, resp.text


# ── 同校写操作不受影响：应 200 ─────────────────────────────


def test_same_school_update_unit_ok(
    client: TestClient, sa_b: User, b_tenant: Tenant, b_unit: Unit
) -> None:
    resp = client.put(
        f"/api/v1/admin/units/{b_unit.id}",
        headers=_token(sa_b, b_tenant.id),
        json={"title": f"乙单元改名-{_uid()}"},
    )
    assert resp.status_code == 200, resp.text


def test_same_school_update_frame_ok(
    client: TestClient, sa_b: User, b_tenant: Tenant, b_frame: SentenceFrame
) -> None:
    resp = client.put(
        f"/api/v1/admin/sentence-frames/{b_frame.id}",
        headers=_token(sa_b, b_tenant.id),
        json={"status": "active"},
    )
    assert resp.status_code == 200, resp.text
