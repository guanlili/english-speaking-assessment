"""备份打包与恢复（wise-quarry-trout 批次12）：数据库 + 音频卷 + manifest。

现状缺口：部署流水线的每日备份只有 pg_dump + .env 快照，AUDIO_STORAGE_DIR
（作答录音 + content 标准音）不在备份里——磁盘故障后数据库恢复不等于
录音可回放。本工具补齐：

- create：pg_dump（经 db 容器执行，宿主机无需 pg_dump）+ 音频目录打包 +
  manifest（时间 / 应用版本 / 迁移版本 / 逐文件 sha256）。空 dump 或
  gzip 失败一律非 0 退出，不产假备份；临时文件用本次专属目录。
- restore：先验 manifest 校验和与包完整性，tar 按成员安全解包（拒绝
  路径穿越/符号链接）；目标库名拒绝开发/生产库名（app/app_test 等）、
  拒绝已存在的库、必须显式 --confirm-target 复述目标名；音频目录必须
  为空或不存在——绝不自动覆盖现有数据。

一致性口径（如实）：在线备份跨数据库与文件系统**不是**天然原子一致——
备份窗口内新上传的录音可能已落盘但行未提交（或反之）。演练用隔离栈
停写后备份；生产如需强一致，在备份窗口短暂停止写入即可，不虚称零丢失。

本脚本不打包明文 .env（配置经部署 Secrets 原渠道重建）；不选异地存储、
不改音频保留天数——RPO/RTO 与异地落点由上线准备时决定。

用法：
  cd backend
  uv run python scripts/backup_bundle.py create --source-db app \
      --audio-dir ../audio --out ../backups/bundle-$(date +%Y%m%d-%H%M).tar.gz
  uv run python scripts/backup_bundle.py restore --bundle <bundle.tar.gz> \
      --target-db restore_drill_x --audio-dir /tmp/restore-audio \
      --confirm-target restore_drill_x
"""

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# 恢复演练绝不许把数据写进这些库（开发/测试/系统库）
DENIED_TARGET_DBS = {"app", "app_test", "postgres", "template0", "template1"}
DUMP_MARKER = "PostgreSQL database dump"


def _fail(message: str) -> SystemExit:
    return SystemExit(f"❌ {message}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compose_db(
    args: list[str], *, input_file: Path | None = None
) -> subprocess.CompletedProcess[bytes]:
    """在 db 容器内执行命令（与部署流水线同姿势，宿主机无需 psql）。"""
    cmd = [
        "docker",
        "compose",
        "-f",
        str(REPO_ROOT / "compose.yml"),
        "exec",
        "-T",
        "db",
        *args,
    ]
    if input_file is not None:
        with input_file.open("rb") as fh:
            return subprocess.run(
                cmd, stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
    return subprocess.run(
        cmd, input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )


def _database_exists(name: str) -> bool:
    result = _compose_db(
        [
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-tAc",
            "SELECT 1 FROM pg_database WHERE datname = '" + name.replace("'", "") + "'",
        ]
    )
    if result.returncode != 0:
        raise _fail(f"无法查询数据库列表：{result.stderr.decode()[:200]}")
    return result.stdout.strip() == b"1"


def _alembic_head(source_db: str) -> str | None:
    result = _compose_db(
        [
            "psql",
            "-U",
            "postgres",
            "-d",
            source_db,
            "-tAc",
            "SELECT version_num FROM alembic_version",
        ]
    )
    if result.returncode != 0:
        return None
    head = result.stdout.decode().strip()
    return head or None


def _app_version() -> str:
    pyproject = REPO_ROOT / "backend" / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text().splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """按成员安全解包：拒绝绝对路径/.. 穿越/符号链接，目标限定 dest 内。"""
    dest_resolved = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if dest_resolved not in target.parents and target != dest_resolved:
            raise _fail(f"归档成员路径越界：{member.name}")
        if member.issym() or member.islnk():
            raise _fail(f"归档含符号链接（拒绝）：{member.name}")
        if member.isdev():
            raise _fail(f"归档含设备文件（拒绝）：{member.name}")
    tar.extractall(dest, filter="data")  # noqa: S202 - 成员已逐一校验


def create_backup(
    source_db: str, audio_dir: Path, out: Path, *, db_args_builder=None
) -> dict:
    """生成备份包（db dump + 音频 tar + manifest），返回 manifest。"""
    if not audio_dir.is_dir():
        raise _fail(f"音频目录不存在：{audio_dir}")
    out.parent.mkdir(parents=True, exist_ok=True)

    runner = db_args_builder or _compose_db
    with tempfile.TemporaryDirectory(prefix="backup-bundle-") as tmp_name:
        tmp = Path(tmp_name)
        dump_path = tmp / "dump.sql"

        # 1) pg_dump（容器内执行）；先落盘再 gzip——失败即非 0，不产假备份
        result = runner(["pg_dump", "-U", "postgres", source_db])
        if result.returncode != 0:
            raise _fail(f"pg_dump 失败：{result.stderr.decode()[:300]}")
        dump_path.write_bytes(result.stdout)
        head = result.stdout[:4096].decode(errors="replace")
        if dump_path.stat().st_size == 0 or DUMP_MARKER not in head:
            raise _fail("pg_dump 输出为空或不是有效 dump（拒绝生成假备份）")

        dump_gz = tmp / "dump.sql.gz"
        with (
            dump_path.open("rb") as src,
            gzip.GzipFile(fileobj=dump_gz.open("wb"), mode="wb") as dst,
        ):
            shutil.copyfileobj(src, dst)
        if dump_gz.stat().st_size == 0:
            raise _fail("gzip 后为空（异常）")

        # 2) 音频目录打包（含 content/ 标准音）；临时目录内构造，避免打包产物自身
        audio_tar = tmp / "audio.tar.gz"
        audio_files = [
            p for p in audio_dir.rglob("*") if p.is_file() and not p.is_symlink()
        ]
        with tarfile.open(audio_tar, "w:gz") as tar:
            for path in sorted(audio_files):
                tar.add(path, arcname=path.relative_to(audio_dir).as_posix())

        # 3) manifest：时间/版本/迁移头/逐文件校验和
        manifest = {
            "schema": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "source_db": source_db,
            "app_version": _app_version(),
            "alembic_head": _alembic_head(source_db),
            "audio_file_count": len(audio_files),
            "consistency_note": (
                "在线备份跨数据库与文件系统并非原子一致；备份窗口内新上传"
                "的录音可能只落了一侧。需要强一致时在备份窗口短暂停写。"
            ),
            "files": {
                "dump.sql.gz": {
                    "sha256": _sha256(dump_gz),
                    "size": dump_gz.stat().st_size,
                },
                "audio.tar.gz": {
                    "sha256": _sha256(audio_tar),
                    "size": audio_tar.stat().st_size,
                },
            },
        }
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 4) 汇总为单包，原子改名落位
        staging = out.with_suffix(out.suffix + ".partial")
        with tarfile.open(staging, "w:gz") as tar:
            tar.add(tmp / "manifest.json", arcname="manifest.json")
            tar.add(dump_gz, arcname="dump.sql.gz")
            tar.add(audio_tar, arcname="audio.tar.gz")
        staging.rename(out)
    return manifest


def restore_bundle(
    bundle: Path, target_db: str, audio_dir: Path, *, confirm_target: str
) -> dict:
    """校验并恢复备份包到隔离目标；返回 manifest（失败抛 SystemExit）。"""
    if target_db in DENIED_TARGET_DBS:
        raise _fail(f"拒绝恢复到开发/测试/系统库：{target_db}")
    if confirm_target != target_db:
        raise _fail("--confirm-target 必须与 --target-db 完全一致（显式确认目标）")
    if _database_exists(target_db):
        raise _fail(f"目标库已存在（不自动覆盖）：{target_db}")
    if audio_dir.exists() and any(audio_dir.iterdir()):
        raise _fail(f"目标音频目录非空（不自动覆盖）：{audio_dir}")

    with tempfile.TemporaryDirectory(prefix="restore-bundle-") as tmp_name:
        tmp = Path(tmp_name)
        try:
            with tarfile.open(bundle, "r:gz") as tar:
                _safe_extract(tar, tmp)
        except tarfile.TarError as exc:
            raise _fail(f"备份包损坏或不是有效归档：{exc}") from exc

        for required in ("manifest.json", "dump.sql.gz", "audio.tar.gz"):
            if not (tmp / required).is_file():
                raise _fail(f"备份包缺少必需文件：{required}")
        manifest = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))

        # 校验和复核：任何成员被改动/损坏即拒绝恢复
        for member, expected in manifest.get("files", {}).items():
            member_path = tmp / member
            actual = _sha256(member_path)
            if actual != expected.get("sha256"):
                raise _fail(f"校验和不匹配（包损坏或被改动）：{member}")

        # 1) 建库（UTF8）并回放 dump；ON_ERROR_STOP 保证回放失败即非 0
        created = _compose_db(
            [
                "psql",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-c",
                f"CREATE DATABASE \"{target_db}\" ENCODING 'UTF8'",
            ]
        )
        if created.returncode != 0:
            raise _fail(f"建库失败：{created.stderr.decode()[:300]}")
        dump_gz = tmp / "dump.sql.gz"
        plain = tmp / "dump.sql"
        with gzip.open(dump_gz, "rb") as src, plain.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        replay = _compose_db(
            [
                "psql",
                "-U",
                "postgres",
                "-d",
                target_db,
                "-v",
                "ON_ERROR_STOP=1",
                "-q",
            ],
            input_file=plain,
        )
        if replay.returncode != 0:
            raise _fail(
                f"dump 回放失败（目标库保留供诊断）：{replay.stderr.decode()[:300]}"
            )

        # 2) 音频安全解包到目标目录
        audio_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tmp / "audio.tar.gz", "r:gz") as tar:
            _safe_extract(tar, audio_dir)

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="生成备份包")
    p_create.add_argument("--source-db", required=True)
    p_create.add_argument("--audio-dir", required=True, type=Path)
    p_create.add_argument("--out", required=True, type=Path)

    p_restore = sub.add_parser("restore", help="恢复到隔离目标")
    p_restore.add_argument("--bundle", required=True, type=Path)
    p_restore.add_argument("--target-db", required=True)
    p_restore.add_argument("--audio-dir", required=True, type=Path)
    p_restore.add_argument("--confirm-target", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_backup(args.source_db, args.audio_dir, args.out)
            print(
                f"✅ 备份完成：{args.out}\n"
                f"   db={args.source_db} 迁移头={manifest['alembic_head']} "
                f"音频文件={manifest['audio_file_count']} 个 "
                f"大小={args.out.stat().st_size} bytes"
            )
        else:
            manifest = restore_bundle(
                args.bundle,
                args.target_db,
                args.audio_dir,
                confirm_target=args.confirm_target,
            )
            print(
                f"✅ 恢复完成：db={args.target_db} 音频目录={args.audio_dir}\n"
                f"   备份时间={manifest.get('created_at')} "
                f"应用版本={manifest.get('app_version')}"
            )
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
