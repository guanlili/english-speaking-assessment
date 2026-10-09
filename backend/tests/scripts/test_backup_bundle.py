"""备份/恢复脚本测试（wise-quarry-trout 批次12）。

分两层：
- 纯逻辑单测（任何环境可跑，含 CI）：拒绝开发/生产目标、确认复述、
  校验和篡改、tar 路径穿越/符号链接、空 dump 拒绝——docker 调用全部
  monkeypatch 假掉。
- 隔离演练（需要本机 docker compose db）：合成数据 → 备份 → 异库恢复
  → 行数与音频逐字节比对 → 自清理。CI 后端 job 无 compose 会跳过，
  本机为真实执行。
"""

import json
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import backup_bundle as bb  # ty: ignore[unresolved-import]  # noqa: E402


def _ok(output: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr=b"")


def _fake_db_runner(*, exists_dbs: set[str] | None = None, dump: bytes | None = None):
    """假容器执行器：只实现脚本用到的 psql/pg_dump 查询面。"""
    exists_dbs = exists_dbs or set()

    def runner(args, *, input_file=None):
        joined = " ".join(args)
        if args[0] == "pg_dump":
            if dump is None:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout=b"", stderr=b"connection refused"
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=dump, stderr=b""
            )
        if "pg_database" in joined:
            import re

            match = re.search(r"datname\s*=\s*'([^']+)'", joined)
            name = match.group(1) if match else ""
            return _ok(b"1" if name in exists_dbs else b"")
        if "alembic_version" in joined:
            return _ok(b"deadbeef")
        # CREATE DATABASE / 回放
        return _ok()

    return runner


VALID_DUMP = b"-- PostgreSQL database dump\n\nCREATE TABLE x (id int);\n"


def _make_bundle(
    tmp_path: Path, *, audio_files: dict[str, bytes] | None = None
) -> Path:
    audio_dir = tmp_path / "audio"
    (audio_dir / "content").mkdir(parents=True)
    (audio_dir / "a.webm").write_bytes(b"attempt-audio")
    (audio_dir / "content" / "std.mp3").write_bytes(b"standard")
    for name, data in (audio_files or {}).items():
        (audio_dir / name).write_bytes(data)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bb, "_compose_db", _fake_db_runner(dump=VALID_DUMP))
    try:
        out = tmp_path / "bundle.tar.gz"
        bb.create_backup("some_db", audio_dir, out)
    finally:
        monkey.undo()
    return out


# ── 纯逻辑：安全拒绝与完整性 ───────────────────────────────────────


def test_restore_refuses_denied_and_unconfirmed_targets(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    for denied in ("app", "app_test", "postgres"):
        with pytest.raises(SystemExit, match="开发/测试/系统库"):
            bb.restore_bundle(bundle, denied, tmp_path / "r", confirm_target=denied)
    with pytest.raises(SystemExit, match="confirm-target"):
        bb.restore_bundle(
            bundle, "restore_drill_ok", tmp_path / "r", confirm_target="other"
        )


def test_restore_refuses_existing_db_and_nonempty_audio(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        bb, "_compose_db", _fake_db_runner(exists_dbs={"restore_drill_taken"})
    )
    try:
        with pytest.raises(SystemExit, match="已存在"):
            bb.restore_bundle(
                bundle,
                "restore_drill_taken",
                tmp_path / "r",
                confirm_target="restore_drill_taken",
            )
    finally:
        monkey.undo()

    busy_dir = tmp_path / "busy"
    busy_dir.mkdir()
    (busy_dir / "keep.webm").write_bytes(b"x")
    monkey.setattr(bb, "_compose_db", _fake_db_runner())
    try:
        with pytest.raises(SystemExit, match="非空"):
            bb.restore_bundle(
                bundle,
                "restore_drill_ok",
                busy_dir,
                confirm_target="restore_drill_ok",
            )
    finally:
        monkey.undo()


def test_restore_rejects_checksum_tamper(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    # 解包改掉 dump 再重打包（不改 manifest 校验和）
    unpack = tmp_path / "unpack"
    with tarfile.open(bundle, "r:gz") as tar:
        tar.extractall(unpack, filter="data")
    (unpack / "dump.sql.gz").write_bytes(b"tampered")
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as tar:
        for name in ("manifest.json", "dump.sql.gz", "audio.tar.gz"):
            tar.add(unpack / name, arcname=name)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bb, "_compose_db", _fake_db_runner())
    try:
        with pytest.raises(SystemExit, match="校验和不匹配"):
            bb.restore_bundle(
                tampered,
                "restore_drill_ok",
                tmp_path / "r",
                confirm_target="restore_drill_ok",
            )
    finally:
        monkey.undo()


def test_restore_rejects_path_traversal_member(tmp_path: Path) -> None:
    _make_bundle(tmp_path)  # 复用构造路径（本用例直接构造恶意包）
    evil = tmp_path / "evil.tar.gz"
    staging = tmp_path / "evil-stage"
    staging.mkdir()
    (staging / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "files": {
                    "dump.sql.gz": {"sha256": "0" * 64},
                    "audio.tar.gz": {"sha256": "0" * 64},
                },
            }
        )
    )
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(staging / "manifest.json", arcname="manifest.json")
        info = tarfile.TarInfo("../../escape.txt")
        payload = b"escaped"
        info.size = len(payload)
        import io

        tar.addfile(info, io.BytesIO(payload))
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bb, "_compose_db", _fake_db_runner())
    try:
        with pytest.raises(SystemExit, match="越界|符号链接|损坏"):
            bb.restore_bundle(
                evil,
                "restore_drill_ok",
                tmp_path / "r",
                confirm_target="restore_drill_ok",
            )
        assert not (tmp_path.parent / "escape.txt").exists()
    finally:
        monkey.undo()


def test_create_rejects_empty_or_invalid_dump(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    monkey = pytest.MonkeyPatch()
    # pg_dump 成功但输出为空
    monkey.setattr(bb, "_compose_db", _fake_db_runner(dump=b""))
    try:
        with pytest.raises(SystemExit, match="空|有效 dump"):
            bb.create_backup("some_db", audio_dir, tmp_path / "b.tar.gz")
        # pg_dump 失败（非 0）
        monkey.setattr(bb, "_compose_db", _fake_db_runner(dump=None))
        with pytest.raises(SystemExit, match="pg_dump 失败"):
            bb.create_backup("some_db", audio_dir, tmp_path / "b.tar.gz")
    finally:
        monkey.undo()


def test_create_rejects_missing_audio_dir(tmp_path: Path) -> None:
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bb, "_compose_db", _fake_db_runner(dump=VALID_DUMP))
    try:
        with pytest.raises(SystemExit, match="音频目录不存在"):
            bb.create_backup("some_db", tmp_path / "nope", tmp_path / "b.tar.gz")
    finally:
        monkey.undo()


# ── 隔离演练（本机 docker compose db；CI 无 compose 自动跳过）──────

_docker_available: bool | None = None


def _docker_ok() -> bool:
    global _docker_available
    if _docker_available is None:
        try:
            _docker_available = bb._compose_db(["pg_dump", "--version"]).returncode == 0
        except Exception:  # noqa: BLE001 - 无 docker/无容器都按不可用处理
            _docker_available = False
    return _docker_available


def test_backup_restore_drill_roundtrip(tmp_path: Path, db) -> None:
    """合成数据 → 备份 → 异库恢复 → 行数与音频逐字节一致 → 自清理。"""
    if not _docker_ok():
        pytest.skip("需要本机 docker compose db（真实演练；CI 后端 job 跳过）")

    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    from sqlmodel import Session, SQLModel

    from app.core.config import settings
    from app.models import Attempt, AttemptStatus

    def db_uri(name: str) -> str:
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(
            str(settings.SQLALCHEMY_DATABASE_TEST_URI)
        )
        return parsed._replace(path=f"/{name}").geturl()

    marker = uuid.uuid4().hex[:8]
    source_db = f"backup_drill_src_{marker}"
    target_db = f"backup_drill_tgt_{marker}"

    admin = create_engine(
        db_uri("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{source_db}"'))
    admin.dispose()

    audio_dir = tmp_path / "audio"
    (audio_dir / "content").mkdir(parents=True)
    attempt_audio = audio_dir / f"{uuid.uuid4()}.webm"
    attempt_audio.write_bytes(f"drill-audio-{marker}".encode())
    (audio_dir / "content" / "std.mp3").write_bytes(b"standard-audio")

    src_engine = create_engine(db_uri(source_db))
    try:
        SQLModel.metadata.create_all(src_engine)
        with Session(src_engine) as session:
            session.add(
                Attempt(
                    item_type="question",
                    item_id=uuid.uuid4(),
                    audio_path=str(attempt_audio),
                    audio_mime="audio/webm",
                    duration_s=5.0,
                    status=AttemptStatus.DONE,
                    transcript=f"drill-{marker}",
                )
            )
            session.commit()

        bundle = tmp_path / "bundle.tar.gz"
        manifest = bb.create_backup(source_db, audio_dir, bundle)
        assert manifest["alembic_head"] is None  # create_all 无迁移表（如实）
        assert manifest["audio_file_count"] == 2

        restored_audio = tmp_path / "restored-audio"
        bb.restore_bundle(bundle, target_db, restored_audio, confirm_target=target_db)

        tgt_engine = create_engine(db_uri(target_db))
        try:
            with tgt_engine.connect() as conn:
                count = conn.execute(text("SELECT count(*) FROM attempt")).scalar_one()
                transcript = conn.execute(
                    text("SELECT transcript FROM attempt LIMIT 1")
                ).scalar_one()
        finally:
            tgt_engine.dispose()
        assert count == 1
        assert transcript == f"drill-{marker}"
        # 音频逐字节一致（含 content 标准音）
        restored_attempt = restored_audio / attempt_audio.name
        assert restored_attempt.read_bytes() == attempt_audio.read_bytes()
        assert (
            restored_audio / "content" / "std.mp3"
        ).read_bytes() == b"standard-audio"
    finally:
        src_engine.dispose()
        admin = create_engine(
            db_uri("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
        )
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{source_db}" WITH (FORCE)'))
            conn.execute(text(f'DROP DATABASE IF EXISTS "{target_db}" WITH (FORCE)'))
        admin.dispose()
