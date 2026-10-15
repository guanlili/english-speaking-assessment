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
        self.assertEqual((bundle / "config.env").stat().st_mode & 0o077, 0)
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


if __name__ == "__main__":
    unittest.main()
