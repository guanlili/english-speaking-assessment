"""孤儿音频扫描（维护工具）：默认 dry-run，只报告不删除。

音频文件名随机（uuid），作答行通过 attempt.audio_path 引用。引用行消失
（课堂删除清历史等）或落盘后入库失败，都会留下无引用文件——它们不受
TTL 清理管理（清理按行驱动），本脚本负责发现与（显式 --apply 时）清除。

安全边界（不满足任一条件的文件绝不删）：
- 只扫描 AUDIO_STORAGE_DIR 根下的普通文件；content/ 子目录（内容标准音/
  TTS 缓存）与其它子目录不碰；
- 跳过近期文件（默认 24h 安全窗口）：上传落盘到入库之间有毫秒级间隙，
  「目录下没查到引用」不等于可以立即删除；
- 跳过符号链接（不追踪其目标）；
- --apply 前只输出清单；删除按解析后仍在存储根内的路径执行。

用法：
  uv run python scripts/audio_orphan_scan.py                 # dry-run
  uv run python scripts/audio_orphan_scan.py --min-age-hours 48
  uv run python scripts/audio_orphan_scan.py --apply         # 实删（慎用）
"""

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

# 允许 `python scripts/audio_orphan_scan.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_MIN_AGE_HOURS = 24.0


def find_orphan_audio_files(
    storage_root: Path,
    referenced_paths: Iterable[str],
    *,
    min_age_hours: float = DEFAULT_MIN_AGE_HOURS,
    now_ts: float | None = None,
) -> list[Path]:
    """返回存储根下无引用且超过安全窗口的普通文件（不删除）。

    referenced_paths 是 attempt.audio_path 的全量字符串集合；引用匹配按
    解析后绝对路径与文件名双重口径（uuid 文件名全局唯一，双口径防 tmp
    目录符号链接差异误判）。
    """
    import time

    root = storage_root.resolve()
    resolved_refs = set()
    name_refs = set()
    for raw in referenced_paths:
        if not raw:
            continue
        resolved_refs.add(str(Path(raw).resolve()))
        name_refs.add(Path(raw).name)

    now = now_ts if now_ts is not None else time.time()
    cutoff = now - min_age_hours * 3600
    orphans: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file() or entry.is_symlink():
            continue  # 子目录（含 content/）、符号链接不碰
        try:
            stat = entry.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            continue  # 安全窗口内：可能是正在入库的上传
        resolved = str(entry.resolve())
        if resolved in resolved_refs or entry.name in name_refs:
            continue
        orphans.append(entry)
    return orphans


def _collect_referenced_paths() -> list[str]:
    from sqlmodel import select

    from app.core.db import engine
    from app.models import Attempt

    from sqlmodel import Session

    with Session(engine) as session:
        return list(
            session.exec(select(Attempt.audio_path)).all()  # type: ignore[arg-type]
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际删除（默认 dry-run 只报告）",
    )
    parser.add_argument(
        "--min-age-hours",
        type=float,
        default=DEFAULT_MIN_AGE_HOURS,
        help=f"安全窗口（小时），窗口内的文件不处理，默认 {DEFAULT_MIN_AGE_HOURS}",
    )
    args = parser.parse_args(argv)

    from app.core.config import settings

    root = Path(settings.AUDIO_STORAGE_DIR)
    if not root.is_dir():
        print(f"存储目录不存在：{root}")
        return 1

    referenced = _collect_referenced_paths()
    orphans = find_orphan_audio_files(
        root, referenced, min_age_hours=args.min_age_hours
    )
    if not orphans:
        print("无孤儿音频。")
        return 0
    for path in orphans:
        print(path)
    total = sum(p.stat().st_size for p in orphans if p.exists())
    print(f"共 {len(orphans)} 个孤儿文件，约 {total / 1024 / 1024:.1f} MB")
    if not args.apply:
        print("dry-run：加 --apply 才会删除。")
        return 0
    root_resolved = root.resolve()
    deleted = 0
    for path in orphans:
        try:
            # 删除前再校验：仍在存储根内、仍无引用窗口内的最近修改
            if root_resolved not in path.resolve().parents:
                continue
            path.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            print(f"删除失败：{path}", file=sys.stderr)
    print(f"已删除 {deleted}/{len(orphans)}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
