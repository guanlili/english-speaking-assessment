"""多租户 B3：平台运营独立身份 + is_superuser 全量替换。

验收点（设计稿 §3.2）：
1. 运营独立登录端点（audience 隔离），/login/platform/me 自述。
2. 学校用户 token 打平台路由 → 401（audience 拒绝）；运营 token 打学校端点 → 401。
3. 校级 admin（旧超管语义）不再有平台权限——不自动升级为跨校运营。
4. is_superuser 从用户模型消失（UserPublic 无此字段）。
5. 业务旁路保留：校级 admin 仍过教师门（classroom_teacher_allowed）。
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import config
from app.models import UserPublic


def test_operator_login_and_me(client: TestClient) -> None:
    """运营登录成功 + me 自述（独立端点/独立身份）。"""
    login_data = {
        "username": config.settings.first_operator_email,
        "password": config.settings.first_operator_password,
    }
    r = client.post(
        f"{config.settings.API_V1_STR}/login/platform-token", data=login_data
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get(f"{config.settings.API_V1_STR}/login/platform/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == config.settings.first_operator_email
    assert "hashed_password" not in body


def test_operator_login_wrong_password(client: TestClient) -> None:
    """运营密码错误统一同文案（不泄露账号存在性）。"""
    r = client.post(
        f"{config.settings.API_V1_STR}/login/platform-token",
        data={
            "username": config.settings.first_operator_email,
            "password": "wrong-pass",
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "账号或密码不正确"


def test_school_user_token_rejected_on_platform_route(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """校级 admin（旧超管）打平台路由 → 401：学校 token 对 platform 受众
    无效（audience 校验拒绝，前端据此登出）——不再自动拥有跨校运营权。"""
    r = client.get(
        f"{config.settings.API_V1_STR}/admin/dashboard/overview",
        headers=superuser_token_headers,
    )
    assert r.status_code == 401


def test_operator_token_rejected_on_school_endpoints(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    """运营 token 不是学校身份：/users/me 与教师门业务端点一律拒收。"""
    r = client.get(
        f"{config.settings.API_V1_STR}/users/me", headers=operator_token_headers
    )
    assert r.status_code == 401
    # 教师门业务端点同样拒收（get_current_user 层面拦截，非业务 403）
    r = client.get(
        f"{config.settings.API_V1_STR}/classes", headers=operator_token_headers
    )
    assert r.status_code == 401


def test_platform_route_requires_operator(client: TestClient) -> None:
    """平台路由匿名 → 401；运营 token → 200。"""
    r = client.get(f"{config.settings.API_V1_STR}/admin/dashboard/overview")
    assert r.status_code == 401
    # overview 的具体路径在下方 dashboard 测试里已覆盖，这里用 metrics 通道
    from tests.utils.utils import get_operator_token_headers

    headers = get_operator_token_headers(client)
    r = client.get(f"{config.settings.API_V1_STR}/admin/metrics", headers=headers)
    assert r.status_code == 200


def test_user_public_has_no_superuser_field(db: Session) -> None:
    """is_superuser 已从用户模型移除（UserPublic 无此字段）。"""
    assert "is_superuser" not in UserPublic.model_fields


def test_school_admin_still_passes_teacher_gates(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """业务旁路保留：校级 admin 仍看全部课堂（旧超管的校内职能不变）。"""
    r = client.get(
        f"{config.settings.API_V1_STR}/classes", headers=superuser_token_headers
    )
    assert r.status_code == 200
