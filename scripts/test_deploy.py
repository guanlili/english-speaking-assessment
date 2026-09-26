"""Deployment regressions; uses Compose parsing only, never starts containers."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="deploy-regression-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        shutil.copy(ROOT / "compose.yml", self.directory / "compose.yml")
        self.env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
        self.env.update(
            SERVER_HOST="example.invalid",
            SERVER_USER="review",
            SERVER_SSH_KEY="fake-key\nmultiline",
            DEPLOY_PATH="/tmp/project path",
            FRONTEND_HOST="https://example.invalid",
            PROJECT_NAME="Review",
            COMPOSE_PROJECT_NAME="review",
            SECRET_KEY="s" * 32,
            FIRST_SUPERUSER="admin@example.com",
            FIRST_SUPERUSER_PASSWORD="fake-password",
            POSTGRES_PASSWORD="fake-db-password",
            APP_PORT="8083",
            WORKERS="1",
            USERS_OPEN_REGISTRATION="false",
            SMTP_HOST="",
            SMTP_USER="",
            SMTP_PASSWORD="",
            EMAILS_FROM_EMAIL="info@example.com",
            SMTP_TLS="True",
            SMTP_SSL="False",
            SMTP_PORT="587",
        )

    def generate(self):
        return subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/generate-deploy-env.sh"),
                str(self.directory / ".env.new"),
            ],
            env=self.env,
            text=True,
            capture_output=True,
        )

    def compose(self):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "--env-file",
                ".env.new",
                "config",
                "--format",
                "json",
            ],
            cwd=self.directory,
            env={
                "PATH": self.env["PATH"],
                "HOME": self.env["HOME"],
                "COMPOSE_ENV_FILE": ".env.new",
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_first_deployment_and_candidate_isolation(self):
        self.assertEqual(self.generate().returncode, 0)
        self.assertFalse((self.directory / ".env").exists())
        config = self.compose()
        self.assertEqual(
            config["services"]["backend"]["environment"]["PROJECT_NAME"], "Review"
        )
        (self.directory / ".env").write_text('PROJECT_NAME="old"\nSMTP_USER="old"\n')
        self.assertEqual(self.compose(), config)
        self.assertEqual((self.directory / ".env.new").stat().st_mode & 0o777, 0o600)

    def test_special_characters(self):
        value = "a$VALUE${OTHER} \"double\" 'single' `backtick` \\slash #hash"
        self.env.update(SECRET_KEY=value, POSTGRES_PASSWORD=value, SMTP_PASSWORD=value)
        self.assertEqual(self.generate().returncode, 0)
        config = self.compose()
        # Compose config escapes literal dollars for round-trippable YAML/JSON.
        for service, key in [
            ("backend", "SECRET_KEY"),
            ("db", "POSTGRES_PASSWORD"),
            ("backend", "SMTP_PASSWORD"),
        ]:
            actual = config["services"][service]["environment"][key]
            self.assertEqual(actual.replace("$$", "$"), value)

    def test_invalid_values_do_not_replace_candidate(self):
        candidate = self.directory / ".env.new"
        for key, value in [
            ("SERVER_HOST", ""),
            ("SECRET_KEY", "  "),
            ("SMTP_PASSWORD", "line\nbreak"),
            ("APP_PORT", "$(id)"),
            ("APP_PORT", "70000"),
        ]:
            with self.subTest(key=key, value=value):
                original = self.env[key]
                self.env[key] = value
                candidate.write_text("unchanged")
                self.assertNotEqual(self.generate().returncode, 0)
                self.assertEqual(candidate.read_text(), "unchanged")
                self.env[key] = original

    def test_example_keys_match_generated_keys(self):
        self.assertEqual(self.generate().returncode, 0)

        def keys(path):
            return {
                line.split("=", 1)[0]
                for line in path.read_text().splitlines()
                if line and not line.startswith("#") and "=" in line
            }

        self.assertEqual(keys(ROOT / ".env.example"), keys(self.directory / ".env.new"))

    def test_workflow_maps_every_secret_key(self):
        """keys 里非派生键必须在 deploy.yml 的 env: 映射出现。

        ARK_TTS_API_KEY 曾只在脚本/键清单里补了、工作流没映射，
        Secret 设了也永远到不了 .env（静默空值）。
        """
        script = (ROOT / "scripts/generate-deploy-env.sh").read_text()
        keys = set(
            re.search(r"^keys=\((.*)\)$", script, re.MULTILINE).group(1).split()
        )
        # 脚本内固定值/派生值键不来自 Secrets，无需映射
        derived = {
            "ENVIRONMENT",
            "POSTGRES_SERVER",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "BACKEND_CORS_ORIGINS",
        }
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
        mapped = set(
            re.findall(r"^ +([A-Z_]+): \$\{\{ secrets\.[A-Z_]+", workflow, re.MULTILINE)
        )
        self.assertEqual(keys - derived - mapped, set())


if __name__ == "__main__":
    unittest.main()
