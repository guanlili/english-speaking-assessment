"""孤儿音频扫描脚本测试：dry-run 默认、安全窗口、content/ 与符号链接不碰。"""

import os
import sys
import uuid
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from audio_orphan_scan import (  # ty: ignore[unresolved-import]  # noqa: E402
    DEFAULT_MIN_AGE_HOURS,
    find_orphan_audio_files,
    main,
)

OLD_TS = 100_000.0  # 远早于安全窗口


def _touch(path: Path, *, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    root.mkdir()
    return root


def test_find_orphans_respects_window_refs_content_and_symlinks(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    referenced = _touch(root / "kept.webm", mtime=OLD_TS)
    orphan = _touch(root / "orphan.webm", mtime=OLD_TS)
    fresh = _touch(root / "fresh.webm")  # 安全窗口内：正在入库的上传
    _touch(root / "content" / "tts.mp3", mtime=OLD_TS)  # 内容标准音：永不碰

    target = tmp_path / "outside.bin"
    target.write_bytes(b"x")
    link = root / "link.webm"
    link.symlink_to(target)  # 符号链接：不追踪不删除

    found = find_orphan_audio_files(
        root,
        [str(referenced)],
        min_age_hours=DEFAULT_MIN_AGE_HOURS,
        now_ts=OLD_TS + DEFAULT_MIN_AGE_HOURS * 3600 + 60,
    )
    assert found == [orphan]
    assert referenced.exists()
    assert fresh.exists()
    assert (root / "content" / "tts.mp3").exists()
    assert link.exists() and target.exists()


def test_find_orphans_matches_by_filename_too(tmp_path: Path) -> None:
    """引用路径因 /tmp 符号链接前缀与磁盘路径不一致时，按文件名兜底匹配。"""
    root = _root(tmp_path)
    audio = _touch(root / f"{uuid.uuid4()}.webm", mtime=OLD_TS)
    # 引用字符串是另一条等价路径（模拟 /tmp vs /private/tmp）
    found = find_orphan_audio_files(
        root,
        [str(tmp_path / "elsewhere" / audio.name)],
        min_age_hours=1.0,
        now_ts=OLD_TS + 7200,
    )
    assert found == []


def test_main_dry_run_by_default_and_apply_deletes(tmp_path: Path, capsys) -> None:
    root = _root(tmp_path)
    orphan = _touch(root / "orphan.webm", mtime=OLD_TS)
    kept = _touch(root / "kept.webm", mtime=OLD_TS)
    referenced = [str(kept)]

    import audio_orphan_scan as scanner  # ty: ignore[unresolved-import]

    orig_collect = scanner._collect_referenced_paths
    scanner._collect_referenced_paths = lambda: referenced
    try:
        import pytest as _pytest

        from app.core.config import settings

        monkeypatcher = _pytest.MonkeyPatch()
        monkeypatcher.setattr(settings, "AUDIO_STORAGE_DIR", str(root))
        try:
            assert main([]) == 0  # dry-run：只报告
            out = capsys.readouterr().out
            assert "dry-run" in out
            assert orphan.exists()

            assert main(["--apply", "--min-age-hours", "1"]) == 0
            assert not orphan.exists()
            assert kept.exists()
        finally:
            monkeypatcher.undo()
    finally:
        scanner._collect_referenced_paths = orig_collect
