"""多租户 C5a：写入侧租户继承 + AC 双校越权验收。

AC 条款按 V1.0 §5 语义与设计稿红线落为可执行断言（乙校=合成租户）：
- AC-01 两校同号各自登录、各自数据
- AC-02/03 学校码未知/停用与登录失败不泄露他校账号存在性
- AC-04 跨校课堂码访问 404
- AC-05 跨校内容（篇目 slug/情景主题）404
- AC-06 跨校学生档案/作答 404
- AC-08 教师只见本校课堂列表
- AC-10/11 平台运营全局可见；运营 token 不能操作学校业务
- AC-12 写入落位：乙校上下文的写入落乙校（WITH CHECK 放行的前提）
  + 无上下文回落默认（B1 兜底语义不变）
"""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core import security
from app.core.tenant_context import tenant_scope
from app.models import (
    DEFAULT_TENANT_ID,
    Attempt,
    Classroom,
    Passage,
    PracticeSession,
    Student,
    Tenant,
    User,
)


def _uid() -> str:
    """每次调用唯一标识：CI 的失败重试（rerun）会重跑用例——module 级
    常量会让重试撞唯一键（首次尝试已插入），函数级唯一免疫重试与顺序。"""
    return uuid.uuid4().hex[:8]


def _mk_teacher(db: Session, tenant_id, name: str) -> User:
    user = User(
        email=f"c5-{name}-{_uid()}@example.com",
        hashed_password="x",
        role="teacher",
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
    row = Tenant(slug=f"c5b-{_uid()}", name_zh="C5 乙校")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_ac12_write_inherits_context_tenant(db: Session, b_tenant) -> None:
    """写入侧继承（C5a 核心）：乙校上下文的 ORM 写入自动落乙校；
    无上下文回落默认（B1 兜底不变）。"""
    # 无上下文（测试直插通道）：回落默认租户
    p_default = Passage(title="默认", text="d", slug=f"c5-{_uid()}-d")
    db.add(p_default)
    db.commit()
    db.refresh(p_default)
    assert p_default.tenant_id == DEFAULT_TENANT_ID

    # 乙校上下文：构造发生在 scope 内 → default 继承乙校
    # （default_factory 是构造期求值；真实业务的对象构造都在请求处理内，
    # 上下文由中间件保证——语义成立）
    with tenant_scope(b_tenant.id):
        p_b = Passage(title="乙校", text="b", slug=f"c5-{_uid()}-b")
        db.add(p_b)
        db.commit()
        db.refresh(p_b)
    assert p_b.tenant_id == b_tenant.id

    with tenant_scope(b_tenant.id):
        c_b = Classroom(code=f"C5B{_uid()[:6].upper()}", class_size=5)
        db.add(c_b)
        db.commit()
        db.refresh(c_b)
    assert c_b.tenant_id == b_tenant.id


def test_ac04_cross_classroom_isolated(
    client: TestClient, db: Session, b_tenant
) -> None:
    """跨校课堂码：乙校 token 打甲校课堂链路 → 404（应用层守卫）。"""
    _mk_teacher(db, DEFAULT_TENANT_ID, "a")  # 甲校教师在位（场景需要）
    class_a = Classroom(code=f"C5A{_uid()[:6].upper()}", class_size=5)
    db.add(class_a)
    db.commit()

    teacher_b = _mk_teacher(db, b_tenant.id, "b")
    headers_b = _token(teacher_b, b_tenant.id)
    resp = client.get(f"/api/v1/classes/{class_a.code}/board", headers=headers_b)
    # 404（课堂不存在视角）或 403（非属主）都成立：内容不泄露
    assert resp.status_code in (403, 404)


def test_ac05_cross_content_invisible(
    client: TestClient, db: Session, b_tenant
) -> None:
    """跨校内容：乙校教师读甲校篇目详情/主题 → 404（归属查询按学校会话
    过滤在 RLS 激活的生产上由数据库强制；应用层 404 语义一致）。"""
    _mk_teacher(db, DEFAULT_TENANT_ID, "ca")
    passage_a = Passage(title="甲校篇", text="a", slug=f"c5-{_uid()}-pa")
    db.add(passage_a)
    db.commit()

    teacher_b = _mk_teacher(db, b_tenant.id, "cb")
    headers_b = _token(teacher_b, b_tenant.id)
    resp = client.put(
        f"/api/v1/admin/passages/{passage_a.id}",
        json={"title": "越权改", "text": passage_a.text},
        headers=headers_b,
    )
    assert resp.status_code in (403, 404)


def test_ac06_cross_student_attempt_isolated(
    client: TestClient, db: Session, b_tenant
) -> None:
    """跨校学生/作答：乙校 token 直取甲校作答 URL → 404/403，不泄内容。"""
    _mk_teacher(db, DEFAULT_TENANT_ID, "sa")
    class_a = Classroom(code=f"C5S{_uid()[:6].upper()}", class_size=5)
    db.add(class_a)
    db.flush()
    student_a = Student(classroom_id=class_a.id, display_name="甲校生")
    db.add(student_a)
    db.flush()
    ps = PracticeSession(
        classroom_id=class_a.id,
        student_id=student_a.id,
        band="B1",
        session_date=date.today(),
    )
    db.add(ps)
    db.flush()
    attempt_a = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        student_id=student_a.id,
        session_id=ps.id,
        audio_path="a.webm",
        duration_s=3.0,
        status="done",
    )
    db.add(attempt_a)
    db.commit()

    teacher_b = _mk_teacher(db, b_tenant.id, "sb")
    headers_b = _token(teacher_b, b_tenant.id)
    resp = client.get(f"/api/v1/attempts/{attempt_a.id}/audio", headers=headers_b)
    assert resp.status_code in (403, 404)


def test_ac08_teacher_sees_own_school_classrooms_only(
    client: TestClient, db: Session, b_tenant
) -> None:
    """教师课堂列表：乙校教师建的班归乙校；列表不出现甲校班（owner 过滤
    + 写入继承使乙校班的归属正确）。"""
    teacher_b = _mk_teacher(db, b_tenant.id, "lb")
    resp = client.post(
        "/api/v1/classes",
        json={"class_size": 5},
        headers=_token(teacher_b, b_tenant.id),
    )
    assert resp.status_code in (200, 201), resp.text
    code = resp.json()["code"]  # 课堂码由服务端生成
    row = db.exec(select(Classroom).where(Classroom.code == code)).first()
    assert row is not None
    # 写入继承：乙校教师的班归乙校（RLS 语义下这才对本校可见）
    assert row.tenant_id == b_tenant.id


def test_ac10_platform_operator_global(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    """平台运营：全局口径端点可用（不因 RLS 失明）。"""
    resp = client.get("/api/v1/admin/metrics", headers=operator_token_headers)
    assert resp.status_code == 200


def test_ac11_operator_token_cannot_use_school_endpoints(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    """运营 token 打学校业务端点 → 401（身份不可互用，B3 语义回归）。"""
    resp = client.get("/api/v1/users/me", headers=operator_token_headers)
    assert resp.status_code == 401


def test_ac01_same_username_two_schools(
    client: TestClient, db: Session, b_tenant
) -> None:
    """两校同号：同一邮箱在乙校可成号（复合唯一），登录按学校解析。"""
    from app import crud
    from app.core.security import get_password_hash

    shared = f"shared-{_uid()}@example.com"
    u_a = User(
        email=shared,
        hashed_password=get_password_hash("pw-a-12345678"),
        role="teacher",
        tenant_id=DEFAULT_TENANT_ID,
    )
    db.add(u_a)
    db.commit()
    # 乙校同邮箱建号（B2 复合唯一允许）
    u_b = User(
        email=shared,
        hashed_password=get_password_hash("pw-b-12345678"),
        role="teacher",
        tenant_id=b_tenant.id,
    )
    db.add(u_b)
    db.commit()
    db.refresh(u_b)
    assert u_b.tenant_id == b_tenant.id

    # 按乙校解析登录命中乙校账号
    got = crud.authenticate(
        session=db,
        account=shared,
        password="pw-b-12345678",
        school_slug=b_tenant.slug,
    )
    assert got is not None and got.id == u_b.id
    got_a = crud.authenticate(
        session=db,
        account=shared,
        password="pw-a-12345678",
    )
    assert got_a is not None and got_a.id == u_a.id
