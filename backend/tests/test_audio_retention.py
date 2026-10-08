"""作答音频保留期清理：只删过期终态作答的音频文件，护栏不碰内容音。"""

import uuid
from datetime import timedelta
from pathlib import Path

from sqlmodel import Session

from app.core.audio_retention import purge_expired_attempt_audio
from app.core.config import settings
from app.models import Attempt, AttemptStatus, get_datetime_utc


def _make_attempt(
    db: Session,
    audio_path: str,
    *,
    status: str,
    age_days: float,
) -> Attempt:
    attempt = Attempt(
        item_id=uuid.uuid4(),
        audio_path=audio_path,
        duration_s=3.0,
        status=status,
        created_at=get_datetime_utc() - timedelta(days=age_days),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def test_ttl_disabled_by_default_keeps_everything(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    audio = tmp_path / "a1.webm"
    audio.write_bytes(b"x")
    _make_attempt(db, str(audio), status=AttemptStatus.DONE, age_days=365)
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 0)

    assert purge_expired_attempt_audio(db) == 0
    assert audio.exists()


def test_ttl_purges_old_terminal_keeps_the_rest(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 90)

    old_done = tmp_path / "old-done.webm"
    old_done.write_bytes(b"x")
    _make_attempt(db, str(old_done), status=AttemptStatus.DONE, age_days=100)

    old_failed = tmp_path / "old-failed.webm"
    old_failed.write_bytes(b"x")
    _make_attempt(db, str(old_failed), status=AttemptStatus.FAILED, age_days=100)

    recent_done = tmp_path / "recent-done.webm"
    recent_done.write_bytes(b"x")
    _make_attempt(db, str(recent_done), status=AttemptStatus.DONE, age_days=10)

    # 排队/评分中的音频仍被 worker 使用：再老也不删
    old_queued = tmp_path / "old-queued.webm"
    old_queued.write_bytes(b"x")
    _make_attempt(db, str(old_queued), status=AttemptStatus.QUEUED, age_days=300)

    # 内容标准音/TTS 缓存：小且必需，永不触碰
    content = tmp_path / "content" / "tts-deadbeef.mp3"
    content.parent.mkdir()
    content.write_bytes(b"x")
    _make_attempt(db, str(content), status=AttemptStatus.DONE, age_days=300)

    # 终态但文件已不存在的行：missing_ok，不报错不计数
    _make_attempt(
        db, str(tmp_path / "gone.webm"), status=AttemptStatus.DONE, age_days=300
    )

    assert purge_expired_attempt_audio(db) == 2
    assert not old_done.exists()
    assert not old_failed.exists()
    assert recent_done.exists()
    assert old_queued.exists()
    assert content.exists()


def test_never_deletes_outside_storage_dir(db: Session, tmp_path: Path, monkeypatch):
    """audio_path 指到存储目录外的文件（异常数据/路径注入）必须跳过。"""
    outside = tmp_path / "outside" / "innocent.webm"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(storage))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 30)
    _make_attempt(db, str(outside), status=AttemptStatus.DONE, age_days=100)

    assert purge_expired_attempt_audio(db) == 0
    assert outside.exists()
