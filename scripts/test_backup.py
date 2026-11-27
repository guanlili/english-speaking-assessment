"""Backup failure/recovery contract with mocked Docker; never touches a real database."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="backup-regression-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project with spaces"
        self.project.mkdir()
        (self.project / ".env").write_text("SECRET_KEY=private-test-value\n")
        audio = self.root / "audio"
        audio.mkdir()
        (audio / "recording.wav").write_bytes(b"recording")
        (audio / "content").mkdir()
        (audio / "content/model.wav").write_bytes(b"model")
        binary = self.root / "bin"
        binary.mkdir()
        commands = {
            "docker": """#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" db "*)
    test "${FAIL_DUMP:-0}" = 0 || exit 1
    test "${EMPTY_DUMP:-0}" = 0 || exit 0
    echo '-- PostgreSQL database dump'
    echo 'CREATE TABLE example(id integer);'
    ;;
  *" backend "*)
    test "${FAIL_AUDIO:-0}" = 0 || exit 1
    python3 -c 'import os,sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz"); archive.add(os.environ["MOCK_AUDIO_DIR"],arcname="."); archive.close()' 
    ;;
  *) exit 2;;
esac
""",
            "git": "#!/usr/bin/env bash\necho 0123456789abcdef\n",
        }
        if not shutil.which("flock"):
            commands["flock"] = """#!/usr/bin/env python3
import fcntl, sys
try:
    fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(1)
"""
        for name, script in commands.items():
            path = binary / name
            path.write_text(script)
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "MOCK_AUDIO_DIR": str(audio),
            # The mock database is a few bytes, so production size/structure
            # floors must be disabled here; they are covered separately by
            # test_size_floor_rejects_shrunken_dump.
            "BACKUP_MIN_DB_BYTES": "0",
            "BACKUP_MIN_AUDIO_BYTES": "0",
            "BACKUP_MIN_TABLES": "0",
        }

    def backup(self, **overrides):
        return subprocess.run(
            ["bash", str(ROOT / "scripts/backup-local.sh"), str(self.project)],
            env={**self.env, **overrides},
            capture_output=True,
            text=True,
        )

    def verify(self, bundle):
        return subprocess.run(
            ["bash", str(ROOT / "scripts/verify-backup.sh"), str(bundle)],
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_complete_bundle_and_corruption_detection(self):
        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        bundles = list((self.project / "backups").glob("bundle-*"))
        self.assertEqual(len(bundles), 1)
        bundle = bundles[0]
        self.assertEqual(self.verify(bundle).returncode, 0)
        # 目录 750 / 文件 640：其他用户无任何权限，同组巡检用户可读 manifest。
        config_mode = (bundle / "config.env").stat().st_mode
        self.assertEqual(config_mode & 0o007, 0)
        self.assertTrue(config_mode & 0o040)
        dir_mode = bundle.stat().st_mode
        self.assertEqual(dir_mode & 0o007, 0)
        self.assertTrue(dir_mode & 0o010)
        audio_files = subprocess.check_output(
            ["tar", "-tzf", str(bundle / "audio.tar.gz")], text=True
        )
        self.assertIn("recording.wav", audio_files)
        self.assertIn("content/model.wav", audio_files)
        (bundle / "database.sql.gz").write_bytes(b"corrupted")
        self.assertNotEqual(self.verify(bundle).returncode, 0)

    def test_failed_or_empty_dump_and_failed_audio_never_publish(self):
        for failure in ["FAIL_DUMP", "EMPTY_DUMP", "FAIL_AUDIO"]:
            with self.subTest(failure=failure):
                self.assertNotEqual(self.backup(**{failure: "1"}).returncode, 0)
                self.assertEqual(list((self.project / "backups").glob("bundle-*")), [])
                self.assertEqual(list((self.project / "backups").glob(".bundle-*")), [])

    def test_manifest_cannot_reference_other_files(self):
        self.assertEqual(self.backup().returncode, 0)
        bundle = next((self.project / "backups").glob("bundle-*"))
        with (bundle / "manifest.sha256").open("a") as stream:
            stream.write("0" * 64 + "  ../../.env\n")
        self.assertNotEqual(self.verify(bundle).returncode, 0)

    def test_size_floor_rejects_shrunken_dump(self):
        # A structurally valid but nearly empty dump (17K in the 2026-11-19 incident)
        # passes gzip/tar checks, so the size floor must abort before publishing.
        result = self.backup(**{"BACKUP_MIN_DB_BYTES": "500000"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("below floor", result.stderr)
        self.assertEqual(list((self.project / "backups").glob("bundle-*")), [])
        self.assertEqual(list((self.project / "backups").glob(".bundle-*")), [])

    def test_table_floor_rejects_schema_only_dump(self):
        result = self.backup(**{"BACKUP_MIN_TABLES": "25"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tables", result.stderr)
        self.assertEqual(list((self.project / "backups").glob("bundle-*")), [])


    def test_retention_prunes_by_name_timestamp_and_drops_broken(self):
        self.assertEqual(self.backup().returncode, 0)
        backups = self.project / "backups"
        # 包名时间戳远早于保留窗口；mtime 刻意留成当前时间，复现「mtime 被重置」场景。
        old = backups / "bundle-20000101T000000Z-OLD0000"
        old.mkdir()
        (old / "database.sql.gz").write_bytes(b"x")
        broken = backups / "bundle-20000102T000000Z-XXXX.BROKEN"
        broken.mkdir()
        (broken / "database.sql.gz").write_bytes(b"x")

        result = self.backup()
        self.assertEqual(result.returncode, 0, result.stderr)
        names = {p.name for p in backups.glob("bundle-*")}
        self.assertNotIn(old.name, names)
        self.assertNotIn(broken.name, names)
        # 两次成功备份各留一个新鲜包。
        self.assertEqual(len([n for n in names if not n.startswith(".")]), 2)


if __name__ == "__main__":
    unittest.main()
