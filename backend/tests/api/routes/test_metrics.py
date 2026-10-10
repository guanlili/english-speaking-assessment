"""运维指标端点（批次 10-10）：superuser 门、计数器语义、队列与存储统计。"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import metrics as metrics_module
from app.core.config import settings


def test_metrics_requires_superuser(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    # 无 token 401；普通教师 403（不触发登出的权限语义）
    assert client.get("/api/v1/admin/metrics").status_code == 401
    teacher = client.post(
        "/api/v1/login/access-token",
        data={"username": "teacher@example.com", "password": "changethis"},
    )
    if teacher.status_code == 200:
        headers = {"Authorization": f"Bearer {teacher.json()['access_token']}"}
        assert client.get("/api/v1/admin/metrics", headers=headers).status_code == 403
    # superuser 200 且三层结构齐备
    resp = client.get("/api/v1/admin/metrics", headers=superuser_token_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"scoring", "providers", "audio_storage"}
    assert "by_status" in body["scoring"]
    assert "oldest_queued_age_s" in body["scoring"]
    assert {"asr", "llm"} <= set(body["providers"].keys())
    for kind in ("asr", "llm"):
        for field in ("calls", "failures", "failure_rate", "avg_seconds"):
            assert field in body["providers"][kind]
    assert {"total_bytes", "file_count"} <= set(body["audio_storage"].keys())


def test_metrics_counter_semantics() -> None:
    metrics_module.reset_for_tests()
    try:
        metrics_module.record_call("llm", ok=True, duration_s=0.5)
        metrics_module.record_call("llm", ok=True, duration_s=1.5)
        metrics_module.record_call("llm", ok=False, duration_s=1.0)
        stats = metrics_module.call_stats()["llm"]
        assert stats["calls"] == 3
        assert stats["failures"] == 1
        assert abs(stats["failure_rate"] - 1 / 3) < 1e-9
        assert abs(stats["avg_seconds"] - 1.0) < 1e-9
        # 空快照 kind 不出现
        assert "asr" not in metrics_module.call_stats()
    finally:
        metrics_module.reset_for_tests()


def test_metrics_audio_storage_stats(
    tmp_path: Path,
    monkeypatch,
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    (tmp_path / "attempt.webm").write_bytes(b"x" * 100)
    content = tmp_path / "content"
    content.mkdir()
    (content / "tts-a.mp3").write_bytes(b"y" * 50)

    from app.api.routes import metrics as route_metrics

    route_metrics._audio_cache = None  # 清缓存直读
    stats = route_metrics._audio_storage_stats()
    assert stats["file_count"] == 2
    assert stats["total_bytes"] == 150


def test_metrics_queue_counts_reflect_attempts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """scoring.by_status 来自 Attempt 聚合：字段结构与计数口径冒烟。"""
    resp = client.get("/api/v1/admin/metrics", headers=superuser_token_headers)
    assert resp.status_code == 200
    scoring = resp.json()["scoring"]
    assert isinstance(scoring["by_status"], dict)
    assert isinstance(scoring["workers_configured"], int)
    assert isinstance(scoring["executor_running"], bool)
