"""基础设施模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    text,
)
from sqlmodel import Field


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# ── 多租户地基（B1）─────────────────────────────────────────────────
# 默认租户用固定 UUID：迁移的 server_default、模型 default 与 initial_data
# 种子三处共用同一常量，保证「写入路径漏设 tenant_id 也会落到默认租户」的
# 单校兼容窗口在 DB 层面成立（设计稿 §9-2「旧进程漏写」的兜底）。
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _current_tenant_or_default() -> uuid.UUID:
    """写入侧租户继承（C5a）：ORM default 取当前上下文租户。

    学校请求的上下文由 C3 中间件从 token tid 注入——乙校教师/学生的
    写入自动落乙校（RLS WITH CHECK 才放行）；无上下文（admin 通道种子、
    测试直插、平台任务未带 scope）回落默认租户（B1 兜底语义不变）。
    """
    from app.core.tenant_context import current_tenant_id

    return current_tenant_id() or DEFAULT_TENANT_ID


def _tenant_id_field() -> Any:
    """租户归属列工厂（B1 锚点定式 + C5a 写入侧继承）。

    default 动态继承当前上下文租户（见 _current_tenant_or_default）；
    server_default 保留固定默认租户（DB 层兜底只服务 admin/迁移通道）。
    """
    return Field(
        default_factory=_current_tenant_or_default,
        foreign_key="tenant.id",
        nullable=False,
        sa_column_kwargs={"server_default": text(f"'{DEFAULT_TENANT_ID}'")},
        index=True,
    )


# ── 五级词库（口语与背单词共用的统一分级数据源，2026-10-03）────────
# 级别固定顺序（越靠前越容易）；实际难度默认取最早、最易一级。
# 与口语分析用的五级词库（vocab_level_entry）完全独立：
# 历史作答的 A2/B1/B2 词汇结果不因五级导入被重新解释。
VOCAB_LEVEL_ORDER = ("KET", "PET", "ACADEMIC", "CET4", "IELTS_TOEFL")
