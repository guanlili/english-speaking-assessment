"""多租户 AC-06/AC-03：导出链路跨校隔离补测。

既有覆盖：test_tenant_c5_acceptance.py 覆盖课堂码/题库内容/作答音频的
跨校 404，test_tenant_c4a_rls.py 覆盖 RLS 策略层；本文件补 /api/v1/exports
（audio_zip 与 student_report_pdf）的 API 级断言——此前该模块无任何租户测试。

断言语义与 RLS 对齐（CLAUDE.md 多租户不变量④：跨校对象按不存在处理，
不泄露存在性）：应用层显式过滤后，无 RLS 的测试/开发环境与生产行为一致。
"""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.models import (
    DEFAULT_TENANT_ID,
    Classroom,
    ExportJob,
    ExportJobStatus,
    ExportKind,
    ExportScope,
    PracticeSession,
    Student,
    Tenant,
    User,
)


def _uid() -> str:
    """函数级唯一：CI rerun 重试会重跑用例，module 级常量会撞唯一键。"""
    return uuid.uuid4().hex[:8]


def _mk_user(db: Session, tenant_id, role: str, name: str) -> User:
    user = User(
        email=f"ex-{name}-{_uid()}@example.com",
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
    row = Tenant(slug=f"ex-{_uid()}", name_zh="导出乙校")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def a_classroom(db: Session) -> Classroom:
    row = Classroom(code=f"EXA{_uid()[:6].upper()}", class_size=5)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_export_job(db: Session, requester: User, tenant_id) -> ExportJob:
    job = ExportJob(
        requester_user_id=requester.id,
        scope=ExportScope.SELF,
        kind=ExportKind.AUDIO_ZIP,
        filter_json={},
        status=ExportJobStatus.SUCCEEDED,
        tenant_id=tenant_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_ac06_cross_tenant_export_read_404(
    client: TestClient, db: Session, b_tenant
) -> None:
    """跨校导出任务：乙校教师/school_admin 按 UUID 读甲校任务 → 404；
    请求者本人可见（正向对照，证明端点本身可用）。"""
    teacher_a = _mk_user(db, DEFAULT_TENANT_ID, "teacher", "ra")
    job_a = _mk_export_job(db, teacher_a, DEFAULT_TENANT_ID)

    resp = client.get(
        f"/api/v1/exports/{job_a.id}",
        headers=_token(teacher_a, DEFAULT_TENANT_ID),
    )
    assert resp.status_code == 200, resp.text

    teacher_b = _mk_user(db, b_tenant.id, "teacher", "rb")
    resp = client.get(
        f"/api/v1/exports/{job_a.id}", headers=_token(teacher_b, b_tenant.id)
    )
    assert resp.status_code == 404, resp.text

    # school_admin 的角色豁免只在本校内成立；跨校同样按不存在处理
    admin_b = _mk_user(db, b_tenant.id, "school_admin", "rb")
    resp = client.get(
        f"/api/v1/exports/{job_a.id}", headers=_token(admin_b, b_tenant.id)
    )
    assert resp.status_code == 404, resp.text


def test_ac06_cross_tenant_export_download_404(
    client: TestClient, db: Session, b_tenant
) -> None:
    """跨校下载：乙校账号打甲校任务的 /download → 404（先于状态码分支）。"""
    teacher_a = _mk_user(db, DEFAULT_TENANT_ID, "teacher", "da")
    job_a = _mk_export_job(db, teacher_a, DEFAULT_TENANT_ID)

    teacher_b = _mk_user(db, b_tenant.id, "teacher", "db")
    resp = client.get(
        f"/api/v1/exports/{job_a.id}/download",
        headers=_token(teacher_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text

    admin_b = _mk_user(db, b_tenant.id, "school_admin", "db")
    resp = client.get(
        f"/api/v1/exports/{job_a.id}/download",
        headers=_token(admin_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac06_export_list_scoped_to_requester(
    client: TestClient, db: Session, b_tenant
) -> None:
    """下载中心列表：只出现本人任务；他校任务不在乙校任何账号的列表里。"""
    teacher_a = _mk_user(db, DEFAULT_TENANT_ID, "teacher", "la")
    job_a = _mk_export_job(db, teacher_a, DEFAULT_TENANT_ID)

    resp = client.get("/api/v1/exports", headers=_token(teacher_a, DEFAULT_TENANT_ID))
    assert resp.status_code == 200, resp.text
    assert str(job_a.id) in [item["id"] for item in resp.json()["data"]]

    teacher_b = _mk_user(db, b_tenant.id, "teacher", "lb")
    resp = client.get("/api/v1/exports", headers=_token(teacher_b, b_tenant.id))
    assert resp.status_code == 200, resp.text
    assert str(job_a.id) not in [item["id"] for item in resp.json()["data"]]


def test_ac03_classroom_audio_export_tampered_404(
    client: TestClient, db: Session, b_tenant, a_classroom
) -> None:
    """入口篡改：乙校教师提交甲校 classroom_id 导课堂录音 → 404
    （跨校对象按不存在处理；RLS 语义下 session.get 同样返回 None）。"""
    teacher_b = _mk_user(db, b_tenant.id, "teacher", "ta")
    resp = client.post(
        "/api/v1/exports",
        json={
            "scope": ExportScope.CLASSROOM,
            "classroom_id": str(a_classroom.id),
            "confirm_contains_student_audio": True,
        },
        headers=_token(teacher_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac03_student_report_tampered_classroom_404(
    client: TestClient, db: Session, b_tenant, a_classroom
) -> None:
    """入口篡改：乙校学生用甲校 classroom_id 申请学情 PDF → 404
    （不落到 403 export_report_forbidden，避免泄露课堂存在性）。"""
    student_b = _mk_user(db, b_tenant.id, "student", "sb")
    resp = client.post(
        "/api/v1/exports",
        json={
            "scope": ExportScope.SELF,
            "kind": ExportKind.STUDENT_REPORT_PDF,
            "classroom_id": str(a_classroom.id),
        },
        headers=_token(student_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac03_class_report_tampered_classroom_404(
    client: TestClient, db: Session, b_tenant, a_classroom
) -> None:
    """入口篡改：乙校教师申请甲校班级分析 PDF → 404。"""
    teacher_b = _mk_user(db, b_tenant.id, "teacher", "cb")
    resp = client.post(
        "/api/v1/exports",
        json={
            "scope": ExportScope.CLASSROOM,
            "kind": ExportKind.CLASS_REPORT_PDF,
            "classroom_id": str(a_classroom.id),
        },
        headers=_token(teacher_b, b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac03_self_scope_tampered_session_no_leak(
    client: TestClient, db: Session, b_tenant
) -> None:
    """入口篡改：乙校账号提交甲校 session_id（scope=self）→ 403，
    与「id 不存在」同响应（RLS 语义），不泄露他校练习轮存在性。"""
    class_a = Classroom(code=f"EXS{_uid()[:6].upper()}", class_size=5)
    db.add(class_a)
    db.flush()
    student_a = Student(classroom_id=class_a.id, display_name="甲校生")
    db.add(student_a)
    db.flush()
    session_a = PracticeSession(
        classroom_id=class_a.id,
        student_id=student_a.id,
        band="B1",
        session_date=date.today(),
    )
    db.add(session_a)
    db.commit()

    teacher_b = _mk_user(db, b_tenant.id, "teacher", "ss")
    resp = client.post(
        "/api/v1/exports",
        json={
            "scope": ExportScope.SELF,
            "session_id": str(session_a.id),
        },
        headers=_token(teacher_b, b_tenant.id),
    )
    assert resp.status_code == 403, resp.text

    # 对照：不存在的 id 同样 403 —— 两种响应一致才不构成存在性预言
    resp = client.post(
        "/api/v1/exports",
        json={
            "scope": ExportScope.SELF,
            "session_id": str(uuid.uuid4()),
        },
        headers=_token(teacher_b, b_tenant.id),
    )
    assert resp.status_code == 403, resp.text
