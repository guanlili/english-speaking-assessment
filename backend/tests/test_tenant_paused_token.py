"""多租户 D2 补强：学校停用（status=paused）对存量 token 即时生效（§5.1）。

修复前：PATCH 停用只挡新登录（入口 404 + authenticate None），已签发
JWT 在自然过期前仍可访问本校业务（200）——get_current_user 只校验
token tid 一致性与 user.is_active，不看租户 status。

修复后语义：
1. active 学校：存量 token 正常访问 200（既有能力不回归）。
2. paused 学校：存量 token 立即 403 Inactive tenant；恢复 active 后同一
   token 又可用（锁住「实时查库、无缓存」的实现承诺）。
3. 平台运营走 get_current_platform_operator（独立表 + 独立 audience），
   不经过学校身份门——停用任意学校，运营端点照常 200。
4. default 租户被 PATCH 守卫永不允许停用（422），存量 token 不受影响。
旁路封堵（学校侧三个身份门同口径）：可选登录通道（音频回放）停用后
静默降级为匿名（401「请先登录」）；多态门（更新日志）同族 403。

状态码选 403 而非 401：凭证本身（签名/密码指纹/tid）全部有效，是
租户级服务暂停，属「已登录但权限不足」；401 会触发前端自动登出，
语义留给 token 无效/过期（AI_RULES「401 vs 403」）。与同一依赖里
Inactive user（403）同族。
"""

import uuid
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.tenant_context import tenant_scope
from app.models import (
    DEFAULT_TENANT_ID,
    Attempt,
    Classroom,
    Student,
    Tenant,
    User,
)

API = settings.API_V1_STR


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _mk_tenant(db: Session, tag: str) -> Tenant:
    row = Tenant(slug=f"pausetk-{tag}-{_uid()}", name_zh=f"停用令牌测试校 {tag}")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_user(db: Session, tenant_id, role: str, tag: str) -> User:
    user = User(
        email=f"pausetk-{tag}-{_uid()}@example.com" if role != "student" else None,
        username=None if role != "student" else f"pausetk-{_uid()}",
        hashed_password="x",
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _token(user: User, tenant_id) -> dict[str, str]:
    """存量 token：登录态签发形态（pwd 指纹绑定库中哈希），直接手签免走登录。"""
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=30),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


def _set_status(
    client: TestClient,
    db: Session,
    operator_headers: dict[str, str],
    tenant: Tenant,
    status: str,
) -> None:
    resp = client.patch(
        f"{API}/admin/tenants/{tenant.id}",
        headers=operator_headers,
        json={"status": status},
    )
    assert resp.status_code == 200, resp.text
    # PATCH 走应用会话已提交；测试共享会话 identity map 里的租户行强制过期
    db.expire_all()


def test_active_tenant_existing_token_ok(client: TestClient, db: Session) -> None:
    """① 学校 active：存量 token 访问本校业务 200（修复不伤正常访问）。"""
    tenant = _mk_tenant(db, "active")
    user = _mk_user(db, tenant.id, "teacher", "a")
    resp = client.get(f"{API}/users/me", headers=_token(user, tenant.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_id"] == str(tenant.id)


def test_paused_tenant_existing_token_rejected(
    client: TestClient, db: Session, operator_token_headers: dict[str, str]
) -> None:
    """② 停用后存量 token 立即 403（Inactive tenant）；恢复 active 后同一
    token 复用 200——判定实时查库，无跨请求缓存时滞。"""
    tenant = _mk_tenant(db, "paused")
    user = _mk_user(db, tenant.id, "teacher", "b")
    headers = _token(user, tenant.id)
    assert client.get(f"{API}/users/me", headers=headers).status_code == 200

    _set_status(client, db, operator_token_headers, tenant, "paused")
    resp = client.get(f"{API}/users/me", headers=headers)
    assert resp.status_code == 403, (resp.status_code, resp.text)
    assert resp.json()["detail"] == "Inactive tenant"

    _set_status(client, db, operator_token_headers, tenant, "active")
    assert client.get(f"{API}/users/me", headers=headers).status_code == 200


def test_operator_unaffected_by_paused_school(
    client: TestClient, db: Session, operator_token_headers: dict[str, str]
) -> None:
    """③ 停用任意学校不影响平台运营：运营门独立身份不经学校侧判定。"""
    tenant = _mk_tenant(db, "op")
    _mk_user(db, tenant.id, "teacher", "c")
    _set_status(client, db, operator_token_headers, tenant, "paused")
    assert (
        client.get(f"{API}/admin/tenants", headers=operator_token_headers).status_code
        == 200
    )
    # 多态门运营分支同样不受学校停用影响
    assert (
        client.get(f"{API}/changelog", headers=operator_token_headers).status_code
        == 200
    )


def test_default_tenant_unaffected(
    client: TestClient, db: Session, operator_token_headers: dict[str, str]
) -> None:
    """④ default 租户不受影响：不允许停用（422），存量 token 照常 200。"""
    assert (
        client.patch(
            f"{API}/admin/tenants/{DEFAULT_TENANT_ID}",
            headers=operator_token_headers,
            json={"status": "paused"},
        ).status_code
        == 422
    )
    other = _mk_tenant(db, "deftk")
    _set_status(client, db, operator_token_headers, other, "paused")
    from tests.utils.utils import get_superuser_token_headers

    resp = client.get(f"{API}/users/me", headers=get_superuser_token_headers(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["tenant_id"] == str(DEFAULT_TENANT_ID)


def test_paused_tenant_optional_audio_channel_degrades(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    """旁路封堵：可选登录通道（音频回放）停用后静默降级匿名——
    active 时本人学生 200，paused 后同一 token 拿到 401「请先登录」。"""
    tenant = _mk_tenant(db, "audio")
    student_user = _mk_user(db, tenant.id, "student", "d")
    with tenant_scope(tenant.id):
        classroom = Classroom(code=f"ptk-{_uid()}", class_size=5)
        db.add(classroom)
        db.flush()
        student = Student(
            classroom_id=classroom.id,
            display_name="停用令牌生",
            user_id=student_user.id,
        )
        db.add(student)
        db.flush()
        attempt = Attempt(
            item_type="question",
            item_id=uuid.uuid4(),
            student_id=student.id,
            audio_path=str(tmp_path / "recording.webm"),
            duration_s=3.0,
            status="done",
        )
        db.add(attempt)
        db.commit()
        attempt_id = attempt.id
    (tmp_path / "recording.webm").write_bytes(b"fake-bytes")

    headers = _token(student_user, tenant.id)
    resp = client.get(f"{API}/attempts/{attempt_id}/audio", headers=headers)
    assert resp.status_code == 200, resp.text

    _set_status(client, db, operator_token_headers, tenant, "paused")
    resp = client.get(f"{API}/attempts/{attempt_id}/audio", headers=headers)
    # token 被降级为匿名 → 归属判定按匿名拒绝（与 is_active=False 同形）
    assert resp.status_code == 401, (resp.status_code, resp.text)
    assert resp.json()["detail"] == "请先登录"


def test_paused_tenant_changelog_school_branch_403(
    client: TestClient, db: Session, operator_token_headers: dict[str, str]
) -> None:
    """旁路封堵：多态门（更新日志）学校分支停用后同族 403，运营分支 200。"""
    tenant = _mk_tenant(db, "chg")
    teacher = _mk_user(db, tenant.id, "teacher", "e")
    headers = _token(teacher, tenant.id)
    assert client.get(f"{API}/changelog", headers=headers).status_code == 200

    _set_status(client, db, operator_token_headers, tenant, "paused")
    assert client.get(f"{API}/changelog", headers=headers).status_code == 403
    assert (
        client.get(f"{API}/changelog", headers=operator_token_headers).status_code
        == 200
    )
