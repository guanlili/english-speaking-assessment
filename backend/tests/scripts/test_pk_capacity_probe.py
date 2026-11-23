import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "pk_capacity_probe.py"
)


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("pk_capacity_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_password_missing_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PK_PROBE_PASSWORD", raising=False)
    module = _load_probe_module()

    with pytest.raises(SystemExit, match="PK_PROBE_PASSWORD"):
        module._require_probe_password()

    assert module.PROBE_PASSWORD == ""


def test_probe_password_loaded_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PK_PROBE_PASSWORD", "local-only-secret")
    module = _load_probe_module()

    module._require_probe_password()

    assert module.PROBE_PASSWORD == "local-only-secret"
