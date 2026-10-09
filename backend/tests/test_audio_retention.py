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


# ── 清理推进 / 上传补偿（wise-quarry-trout 批次06）──────────────────


def _make_batch_attempts(
    db: Session, storage: Path, count: int, *, age_days: float = 100
) -> list[Attempt]:
    rows = []
    for i in range(count):
        audio = storage / f"bulk-{i:05d}.webm"
        audio.write_bytes(b"x")
        row = _make_attempt(
            db, str(audio), status=AttemptStatus.DONE, age_days=age_days
        )
        rows.append(row)
    return rows


def test_purge_progresses_past_batch_limit(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    """1200 条候选（> 单轮 500 上限）：连续调用必须全部推进，不再卡死第一批。"""
    from app.core.audio_retention import PURGE_BATCH_LIMIT

    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 90)
    rows = _make_batch_attempts(db, tmp_path, 1200)

    total_deleted = 0
    rounds = 0
    while True:
        deleted = purge_expired_attempt_audio(db)
        total_deleted += deleted
        rounds += 1
        if deleted == 0:
            break
        assert rounds <= 10, "清理未推进：疑似反复选中同一批记录"
    assert total_deleted == 1200
    assert rounds >= 1200 // PURGE_BATCH_LIMIT  # 确实经过了多轮
    for row in rows:
        db.refresh(row)
        assert row.audio_purged_at is not None
    # 全部文件删除、全部行带完成标记（下一轮候选为空）
    assert purge_expired_attempt_audio(db) == 0


def test_purge_settles_missing_and_out_of_bounds(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    """文件缺失/越界路径：结算标记但不计删除数，且不再重复选中。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 90)

    missing = _make_attempt(
        db, str(tmp_path / "gone.webm"), status=AttemptStatus.DONE, age_days=100
    )
    outside = tmp_path / "elsewhere" / "keep.webm"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    out_row = _make_attempt(db, str(outside), status=AttemptStatus.DONE, age_days=100)

    assert purge_expired_attempt_audio(db) == 0  # 无文件被删
    db.refresh(missing)
    db.refresh(out_row)
    assert missing.audio_purged_at is not None  # 缺失 → 结算
    assert out_row.audio_purged_at is not None  # 越界 → 结算不删
    assert outside.exists()
    # 已结算的行不再进入候选
    assert purge_expired_attempt_audio(db) == 0


def test_purge_retries_after_delete_failure(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    """删除失败不标记、下一轮重试成功。"""

    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 90)
    audio = tmp_path / "flaky.webm"
    audio.write_bytes(b"x")
    row = _make_attempt(db, str(audio), status=AttemptStatus.DONE, age_days=100)

    real_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "flaky.webm":
            raise OSError("disk busy")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    assert purge_expired_attempt_audio(db) == 0
    db.refresh(row)
    assert row.audio_purged_at is None  # 失败不结算
    assert audio.exists()

    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert purge_expired_attempt_audio(db) == 1
    db.refresh(row)
    assert row.audio_purged_at is not None
    assert not audio.exists()


def test_purge_settles_symlink_pointing_outside(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    """存储内的符号链接指向外部真实文件：resolve 后按越界结算，外部文件保留。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 90)
    victim = tmp_path.parent / "real-target.webm"
    victim.write_bytes(b"x")
    link = tmp_path / "sneaky.webm"
    link.symlink_to(victim)
    row = _make_attempt(db, str(link), status=AttemptStatus.DONE, age_days=100)

    assert purge_expired_attempt_audio(db) == 0
    db.refresh(row)
    assert row.audio_purged_at is not None
    assert victim.exists()  # 真实文件绝不被删


def test_purge_settles_same_dir_symlink_without_deleting_target(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    """返修E：存储根内的符号链接指向同目录另一条音频——原路径即链接，
    resolve 前拒绝，目标文件（可能仍被其它作答引用）绝不被删。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "AUDIO_TTL_DAYS", 90)
    target = tmp_path / "live-audio.webm"
    target.write_bytes(b"x")
    link = tmp_path / "alias.webm"
    link.symlink_to(target)
    # 目标本身仍被一条未过期作答引用
    _make_attempt(db, str(target), status=AttemptStatus.DONE, age_days=10)
    link_row = _make_attempt(db, str(link), status=AttemptStatus.DONE, age_days=100)

    assert purge_expired_attempt_audio(db) == 0
    db.refresh(link_row)
    assert link_row.audio_purged_at is not None  # 链接行结算
    assert target.exists()  # 目标音频保留
