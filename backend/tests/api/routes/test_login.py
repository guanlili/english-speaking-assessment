from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.crud import create_user
from app.models import User, UserCreate
from app.utils import generate_password_reset_token
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
@pytest.mark.parametrize("registration", [False, True])
@pytest.mark.parametrize("email_enabled", [False, True])
def test_login_options_match_server_settings(
    client: TestClient, environment: str, registration: bool, email_enabled: bool
) -> None:
    with (
        patch.object(settings, "ENVIRONMENT", environment),
        patch.object(settings, "USERS_OPEN_REGISTRATION", registration),
        patch.object(
            settings, "SMTP_HOST", "smtp.example.com" if email_enabled else None
        ),
        patch.object(settings, "EMAILS_FROM_EMAIL", "support@example.com"),
    ):
        response = client.get("/api/v1/login/options")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "demo_enabled": environment == "local",
        "registration_enabled": registration,
        "password_recovery_enabled": email_enabled,
    }


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_demo_login_blocked_outside_local(client: TestClient, environment: str) -> None:
    with patch.object(settings, "ENVIRONMENT", environment):
        response = client.post("/api/v1/login/demo")
    assert response.status_code == 404
    assert "access_token" not in response.json()


@pytest.mark.parametrize("missing_setting", ["SMTP_HOST", "EMAILS_FROM_EMAIL"])
def test_password_recovery_disabled_without_email(
    client: TestClient, missing_setting: str
) -> None:
    with (
        patch.object(settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "support@example.com"),
        patch.object(settings, missing_setting, None),
        patch("app.api.routes.login.send_email") as send_email,
    ):
        assert (
            client.get("/api/v1/login/options").json()["password_recovery_enabled"]
            is False
        )
        for email in (settings.FIRST_SUPERUSER, random_email()):
            response = client.post(f"/api/v1/password-recovery/{email}")
            assert response.status_code == 503
            assert response.json() == {
                "detail": "邮件找回暂不可用，请联系学校管理员重置密码"
            }
        send_email.assert_not_called()


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch.object(settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "support@example.com"),
        patch("app.api.routes.login.send_email") as send_email,
    ):
        email = settings.EMAIL_TEST_USER
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }
        send_email.assert_called_once()
        assert send_email.call_args.kwargs["email_to"] == email


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch.object(settings, "SMTP_HOST", "smtp.example.com"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "support@example.com"),
        patch("app.api.routes.login.send_email") as send_email,
    ):
        email = random_email()
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }
        send_email.assert_not_called()


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user_create = UserCreate(
        email=email,
        full_name="Test User",
        password=password,
        is_active=True,
        is_superuser=False,
    )
    user = create_user(session=db, user_create=user_create)
    token = generate_password_reset_token(
        email=email, password_hash=user.hashed_password
    )
    headers = user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    """Test that logging in with a bcrypt password hash upgrades it to argon2."""
    email = random_email()
    password = random_lower_string()

    # Create a bcrypt hash directly (simulating legacy password)
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt hashes start with $2

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.hashed_password.startswith("$2")

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    # Verify the hash was upgraded to argon2
    assert user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    # Should not need another update since it's already argon2
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    """Test that logging in with an argon2 password hash does not update it."""
    email = random_email()
    password = random_lower_string()

    # Create an argon2 hash (current default)
    argon2_hash = get_password_hash(password)
    assert argon2_hash.startswith("$argon2")

    # Create user with argon2 hash
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    original_hash = user.hashed_password

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    assert user.hashed_password == original_hash
    assert user.hashed_password.startswith("$argon2")


def test_use_invalid_token_returns_401(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert r.status_code == 401
    # 401 必须带 WWW-Authenticate；403 留给"已登录但权限不足"（不触发前端登出）
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_demo_login_issues_admin_token(client: TestClient) -> None:
    """演示登录（仅 local）：token 可访问管理端接口。"""
    resp = client.post("/api/v1/login/demo")
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["is_superuser"] is True


def test_password_change_invalidates_old_tokens(
    client: TestClient, db: Session
) -> None:
    """改密后旧 token 立即失效（pwd 声明绑定签发时的密码哈希前缀）。"""
    from tests.utils.utils import get_superuser_token_headers

    old_headers = get_superuser_token_headers(client)
    old_password = settings.FIRST_SUPERUSER_PASSWORD
    new_password = random_lower_string() + "1a!"
    try:
        resp = client.patch(
            f"{settings.API_V1_STR}/users/me/password",
            headers=old_headers,
            json={"current_password": old_password, "new_password": new_password},
        )
        assert resp.status_code == 200
        # 旧 token：401（凭证已失效，前端登出重新登录）
        stale = client.post(
            f"{settings.API_V1_STR}/login/test-token", headers=old_headers
        )
        assert stale.status_code == 401
        # 新密码可登录，且新 token 可用
        login = client.post(
            f"{settings.API_V1_STR}/login/access-token",
            data={"username": settings.FIRST_SUPERUSER, "password": new_password},
        )
        assert login.status_code == 200
        fresh_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get(f"{settings.API_V1_STR}/users/me", headers=fresh_headers)
        assert me.status_code == 200
    finally:
        # 恢复超级管理员密码，避免影响后续用例的 fixture 登录
        user = db.exec(
            select(User).where(User.email == settings.FIRST_SUPERUSER)  # type: ignore[attr-defined]
        ).first()
        assert user is not None
        user.hashed_password = get_password_hash(old_password)
        db.add(user)
        db.commit()


def test_login_rate_limit_per_account(client: TestClient) -> None:
    """账号维度限流：同一账号连错达到上限后 429，且不影响其他账号。"""
    from app.api.routes import login as login_route

    try:
        for _ in range(login_route.LOGIN_RATE_LIMIT):
            resp = client.post(
                f"{settings.API_V1_STR}/login/access-token",
                data={"username": "nobody-unknown", "password": "wrong"},
            )
            assert resp.status_code == 400
        blocked = client.post(
            f"{settings.API_V1_STR}/login/access-token",
            data={"username": "nobody-unknown", "password": "wrong"},
        )
        assert blocked.status_code == 429
        # testclient 共享同一 IP，上面的失败也灌满了 IP 桶；
        # 清掉共享状态以模拟"换一台设备"，验证账号维度的计数不会跨账号生效
        with login_route._login_lock:
            login_route._login_attempts.clear()
        # 其他账号不受该账号的失败计数影响
        other = client.post(
            f"{settings.API_V1_STR}/login/access-token",
            data={"username": settings.FIRST_SUPERUSER, "password": "wrong"},
        )
        assert other.status_code == 400
    finally:
        # 清理内存限流表，避免污染同会话后续用例（testclient 共享同一 IP 桶）
        with login_route._login_lock:
            login_route._login_attempts.clear()
