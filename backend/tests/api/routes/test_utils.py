import asyncio
import struct
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_check_lightweight(client: TestClient) -> None:
    """存活检查：不依赖数据库，恒 200"""
    r = client.get(f"{settings.API_V1_STR}/utils/health-check/")
    assert r.status_code == 200
    assert r.json() is True


def test_ready_check_with_database(client: TestClient) -> None:
    """就绪检查：数据库可用时返回 200"""
    r = client.get(f"{settings.API_V1_STR}/utils/ready-check/")
    assert r.status_code == 200
    assert r.json() == {"message": "Ready"}


def test_ready_check_fails_when_db_down(client: TestClient) -> None:
    """就绪检查：数据库查询失败时返回 503，且不泄露内部异常细节"""

    with patch(
        "app.api.routes.utils.probe_database", side_effect=RuntimeError("private host")
    ):
        r = client.get(f"{settings.API_V1_STR}/utils/ready-check/")
    assert r.status_code == 503
    assert r.json() == {"detail": "Service not ready"}
    assert "private host" not in r.text


def test_ready_check_timeout_and_recovery(client: TestClient) -> None:
    cancelled = False

    async def stalled_probe(_dsn: str) -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(60)
        finally:
            cancelled = True

    with (
        patch("app.api.routes.utils.probe_database", stalled_probe),
        patch("app.api.routes.utils.READINESS_TIMEOUT_SECONDS", 0.05),
    ):
        start = time.monotonic()
        r = client.get(f"{settings.API_V1_STR}/utils/ready-check/")
        assert time.monotonic() - start < 1
    assert r.status_code == 503
    assert cancelled
    assert client.get(f"{settings.API_V1_STR}/utils/ready-check/").status_code == 200


def test_recover_password_without_email_configured(client: TestClient) -> None:
    """找回密码：邮件未配置时不再 500，仍返回防枚举的成功文案，且不尝试发信"""
    with (
        patch("app.api.routes.login.settings") as mock_settings,
        patch("app.api.routes.login.send_email") as mock_send,
    ):
        mock_settings.emails_enabled = False
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{settings.FIRST_SUPERUSER}"
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }
        mock_send.assert_not_called()


@pytest.mark.parametrize("after_handshake", [False, True])
def test_ready_check_silent_tcp_peer(after_handshake: bool) -> None:
    """An accepted TCP connection that never speaks PostgreSQL must time out."""
    from fastapi import HTTPException

    from app.api.routes.utils import ready_check

    async def scenario() -> None:
        peers: list[asyncio.StreamWriter] = []
        query_received = asyncio.Event()

        async def accept(
            _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            peers.append(writer)
            if after_handshake:
                # Minimal PostgreSQL startup exchange; then never answer SELECT 1.
                size = struct.unpack("!I", await _reader.readexactly(4))[0]
                await _reader.readexactly(size - 4)

                def packet(kind: bytes, body: bytes) -> bytes:
                    return kind + struct.pack("!I", len(body) + 4) + body

                writer.write(
                    packet(b"R", struct.pack("!I", 0))
                    + packet(b"S", b"server_version\x0018.0\x00")
                    + packet(b"S", b"client_encoding\x00UTF8\x00")
                    + packet(b"Z", b"I")
                )
                await writer.drain()
                if await _reader.read(1024):
                    query_received.set()

        server = await asyncio.start_server(accept, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with patch("app.api.routes.utils.READINESS_TIMEOUT_SECONDS", 0.1):
                start = time.monotonic()
                try:
                    await ready_check(
                        f"postgresql://review:fake@127.0.0.1:{port}/review?sslmode=disable"
                    )
                except HTTPException as exc:
                    assert exc.status_code == 503
                else:
                    raise AssertionError("Silent peer unexpectedly passed readiness")
                assert time.monotonic() - start < 1
                assert peers
                if after_handshake:
                    assert query_received.is_set()
        finally:
            server.close()
            for peer in peers:
                peer.close()
                await peer.wait_closed()
            await server.wait_closed()

    asyncio.run(scenario())
