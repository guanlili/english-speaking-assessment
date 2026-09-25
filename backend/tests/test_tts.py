"""标准音：TTS provider、内容音频存取、上传与回放端点。"""

import httpx
import pytest

from app.core.config import settings
from app.scoring.tts import ArkTtsProvider, TtsError


def test_tts_requires_api_key() -> None:
    provider = ArkTtsProvider(api_key=None, model="m", voice="v")
    with pytest.raises(TtsError, match="ARK_API_KEY"):
        provider.synthesize("hello")


def test_tts_synthesize_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert request.url.path == "/v1/audio/speech"
        assert body["input"] == "Dogs are friendly."
        assert body["response_format"] == "mp3"
        return httpx.Response(200, content=b"ID3-mp3-bytes")

    provider = ArkTtsProvider(
        api_key="key",
        model="tts-model",
        voice="en_voice",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert provider.synthesize("Dogs are friendly.") == b"ID3-mp3-bytes"


def test_tts_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    provider = ArkTtsProvider(
        api_key="key",
        model="m",
        voice="v",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(TtsError, match="404"):
        provider.synthesize("hello")


def test_content_audio_save_and_resolve(tmp_path, monkeypatch) -> None:
    from app.core.storage import (
        content_audio_path,
        content_audio_url,
        save_content_audio,
    )

    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="不支持"):
        save_content_audio(b"x", ".exe")
    path = save_content_audio(b"mp3data", ".mp3")
    resolved = content_audio_path(path.name)
    assert resolved == path
    assert resolved is not None and resolved.read_bytes() == b"mp3data"
    assert content_audio_url(path.name).endswith(path.name)
    # 目录穿越与不存在文件
    assert content_audio_path("../etc/passwd") is None
    assert content_audio_path("nonexistent.mp3") is None


def test_upload_and_serve_content_audio(
    client, superuser_token_headers, monkeypatch, tmp_path
) -> None:
    """上传现成音频 → 回放端点取回字节；未授权 401；非法后缀 422。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    payload = b"fake-mp3-bytes"

    resp = client.post(
        "/api/v1/admin/audio/upload",
        files={"file": ("standard.mp3", payload, "audio/mpeg")},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["audio_url"]
    assert url.startswith("/api/v1/audio/content/")

    played = client.get(url)
    assert played.status_code == 200
    assert played.content == payload
    assert played.headers["content-type"].startswith("audio/mpeg")

    # 未授权
    assert (
        client.post(
            "/api/v1/admin/audio/upload",
            files={"file": ("a.mp3", b"x", "audio/mpeg")},
        ).status_code
        == 401
    )
    # 非法后缀
    bad = client.post(
        "/api/v1/admin/audio/upload",
        files={"file": ("evil.exe", b"x", "application/octet-stream")},
        headers=superuser_token_headers,
    )
    assert bad.status_code == 422
    # 不存在的回放 404
    assert client.get("/api/v1/audio/content/nope.mp3").status_code == 404


def test_tts_endpoint_without_key_returns_503(
    client, superuser_token_headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "ARK_API_KEY", None)
    monkeypatch.setattr(settings, "ARK_TTS_API_KEY", None)
    resp = client.post(
        "/api/v1/admin/audio/tts",
        json={"text": "hello"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 503
    assert "上传" in resp.json()["detail"] or "ARK_API_KEY" in resp.json()["detail"]
