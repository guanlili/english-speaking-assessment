import random
import string

from fastapi.testclient import TestClient

from app.core.config import settings


def random_lower_string() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=32))


def random_email() -> str:
    return f"{random_lower_string()}@{random_lower_string()}.com"


def get_superuser_token_headers(client: TestClient) -> dict[str, str]:
    """校级 admin 登录（B3 起首超管账号=本校管理员，无全局绕过语义）。"""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    return headers


def get_operator_token_headers(client: TestClient) -> dict[str, str]:
    """平台运营登录（B3 独立身份）：独立端点 + 独立 audience token。

    种子凭据默认沿用首超管（config.first_operator_* 的过渡窗口回退），
    init_db 按同一回退创建运营账号，故测试直接用 FIRST_SUPERUSER 凭据。
    """
    login_data = {
        "username": settings.first_operator_email,
        "password": settings.first_operator_password,
    }
    r = client.post(f"{settings.API_V1_STR}/login/platform-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    return headers
