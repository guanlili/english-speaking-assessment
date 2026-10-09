"""孤儿音频扫描脚本测试：dry-run 默认、安全窗口、content/ 与符号链接不碰。"""

import os
import sys
import uuid
from pathlib import Path

import pytest

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


def test_invalid_min_age_rejected() -> None:
    """返修E：负数/零/NaN 安全窗口直接拒绝，不会把窗口变成立即删除。"""
    for bad in ("0", "-1", "nan", "inf"):
        with pytest.raises(SystemExit) as exc:
            main(["--min-age-hours", bad])
        assert exc.value.code == 2  # argparse error 退出码


def test_apply_rechecks_references_added_after_scan(tmp_path: Path, capsys) -> None:
    """返修E：候选选出后、--apply 执行前新增的引用必须救回该文件。"""
    import audio_orphan_scan as scanner  # ty: ignore[unresolved-import]

    root = _root(tmp_path)
    orphan = _touch(root / "now-referenced.webm", mtime=OLD_TS)

    refs = {"collected": []}

    def fake_collect():
        # 第一次（初筛）无引用；第二次（apply 复验）出现新引用
        if refs["collected"]:
            return [str(orphan)]
        refs["collected"].append(True)
        return []

    orig_collect = scanner._collect_referenced_paths
    scanner._collect_referenced_paths = fake_collect
    try:
        from app.core.config import settings

        mp = pytest.MonkeyPatch()
        mp.setattr(settings, "AUDIO_STORAGE_DIR", str(root))
        try:
            assert main(["--apply", "--min-age-hours", "1"]) == 0
            out = capsys.readouterr().out
            assert "已删除 0/1" in out
            assert orphan.exists()  # 复验救回
        finally:
            mp.undo()
    finally:
        scanner._collect_referenced_paths = orig_collect


def test_apply_rechecks_mtime_after_scan(tmp_path: Path, capsys) -> None:
    """返修E：候选选出后被改写（窗口内 mtime）的文件不删。"""
    import os

    import audio_orphan_scan as scanner  # ty: ignore[unresolved-import]

    root = _root(tmp_path)
    orphan = _touch(root / "touched-after-scan.webm", mtime=OLD_TS)

    orig_collect = scanner._collect_referenced_paths
    scanner._collect_referenced_paths = lambda: []
    # 初筛完成后、删除前把 mtime 拉回现在：模拟上传复用同名文件
    orig_find = scanner.find_orphan_audio_files

    def touch_then_find(*args, **kwargs):
        found = orig_find(*args, **kwargs)
        os.utime(orphan, None)  # now
        return found

    scanner.find_orphan_audio_files = touch_then_find
    try:
        from app.core.config import settings

        mp = pytest.MonkeyPatch()
        mp.setattr(settings, "AUDIO_STORAGE_DIR", str(root))
        try:
            assert main(["--apply", "--min-age-hours", "1"]) == 0
            assert orphan.exists()  # 窗口内改动 → 不删
        finally:
            mp.undo()
    finally:
        scanner._collect_referenced_paths = orig_collect
        scanner.find_orphan_audio_files = orig_find
