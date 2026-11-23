"""锚点校模块种子口径：生产不得写演示词汇双开。"""

from app.core.db import _anchor_module_defaults
from app.models import MODULE_SPEAKING, MODULE_VOCABULARY


def test_production_anchor_only_speaking_enabled() -> None:
    defaults = _anchor_module_defaults("production")
    assert defaults[MODULE_SPEAKING] is True
    assert defaults[MODULE_VOCABULARY] is False


def test_local_and_staging_anchor_keep_demo_double_on() -> None:
    for env in ("local", "staging"):
        defaults = _anchor_module_defaults(env)
        assert defaults[MODULE_SPEAKING] is True
        assert defaults[MODULE_VOCABULARY] is True
