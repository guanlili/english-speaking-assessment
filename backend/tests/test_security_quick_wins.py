"""安全快赢包测试：通用限流器、signup/attempts 限流、后端安全响应头。"""

from fastapi.testclient import TestClient

from app.api.routes import attempts as attempts_route
from app.api.routes import users as users_route
from app.core.ratelimit import SlidingWindowLimiter
from tests.utils.audio import wav_upload
from tests.utils.utils import random_email, random_lower_string


def test_sliding_window_limiter_semantics() -> None:
    limiter = SlidingWindowLimiter(limit=3, window_s=300)
    for _ in range(3):
        limiter.check("b")
    try:
        limiter.check("b")
        raise AssertionError("应抛 429")
    except AssertionError:
        raise
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 429
    # 其它桶不受影响
    limiter.check("other")
    # 成功清桶后恢复
    limiter.record_success("b")
    limiter.check("b")


def test_signup_rate_limited_per_ip(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(users_route._signup_limiter, "limit", 3)
    users_route._signup_limiter._attempts.clear()

    codes = [
        client.post(
            "/api/v1/users/signup",
            json={"email": random_email(), "password": random_lower_string()},
        ).status_code
        for _ in range(4)
    ]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    users_route._signup_limiter._attempts.clear()


def test_attempt_upload_rate_limited_without_student(
    client: TestClient, superuser_token_headers: dict[str, str], monkeypatch
) -> None:
    """无学生归属的提交（匿名演示/超管）按 IP 限流。

    用不存在的题目 id：限流在题目解析之前，前两次会走到 404（题目不存在），
    第三次撞 429——计数发生在响应成败之前才是有效防线。
    """
    monkeypatch.setattr(attempts_route._attempt_ip_limiter, "limit", 2)
    attempts_route._attempt_ip_limiter._attempts.clear()

    codes = [
        client.post(
            "/api/v1/attempts",
            files={"audio": wav_upload(1.5)},
            data={
                "item_type": "repeat",
                "item_id": "00000000-0000-0000-0000-000000000001",
                "duration_s": "1.5",
            },
            headers=superuser_token_headers,
        ).status_code
        for _ in range(3)
    ]
    assert codes[:2] == [404, 404]
    assert codes[2] == 429
    attempts_route._attempt_ip_limiter._attempts.clear()


def test_api_responses_carry_security_headers(client: TestClient) -> None:
    resp = client.get("/api/v1/utils/health-check/")
    assert resp.status_code == 200
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
