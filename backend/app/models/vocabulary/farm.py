"""词汇第三批：专注农场——成长地块、收获与既有激励边界。

边界（设计稿 `docs/vocabulary-pk-farm-design-20261122.md` §4）：

- **成长事件**：只认任务练习 / 自主练习 / FSRS 复习的**首答**
  （``attempt_no=1``）；测验（quiz）不计；切屏、空闲不产生成长。
- **跨班连续**：地块按登录账号 ``user_id`` 归属（同一账号换班后继续保留），
  不是某一班的学生档案；历史班级作答与快照不被迁移或重写。
- **不新造并行积分**：收获 XP 写入既有 ``student.xp``（当前课堂档案），
  复用既有 ``student_badge`` 账本；不另立积分字段/表/排行榜。
- **streak 不被农场推进或重置**：连胜口径仍只由口语每日计划结算推进。
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import _tenant_id_field, get_datetime_utc

# ── 成长口径（设计稿 §4，可验收数值）─────────────────────────────────
# 4 阶段阈值：0 / 5 / 12 / 20 点；≥20 为成熟可收获
STAGE_THRESHOLDS: tuple[int, int, int, int] = (0, 5, 12, 20)
MATURE_POINTS = STAGE_THRESHOLDS[-1]
# 每个有效首答 +1 点；每日最多计 30 点（跨自然日按 PRACTICE_TZ 重置）
GROWTH_PER_EVENT = 1
GROWTH_DAILY_CAP = 30
# 成熟后收获一次 +10 XP；每日农场 XP 上限 10（防止刷分）
HARVEST_XP = 10
FARM_XP_DAILY_CAP = 10

# 农场徽章 key（落既有 student_badge 表，不建第二套）
BADGE_FARM_FIRST_HARVEST = "farm_first_harvest"
BADGE_FARM_HARVEST_7 = "farm_harvest_7"
HARVEST_COUNT_BADGE = 7

# 徽章来源标注（农场视图只读展示，不改变既有结算口径）
BADGE_SOURCE_FARM = "专注农场"
BADGE_SOURCE_CLASSROOM = "课堂档案/每日计划"


class VocabFarmPlot(SQLModel, table=True):
    """一个登录账号一块地：成长点数、每日计数、收获次数与留痕。

    ``growth_points`` 是当前地块上可生长的点数（收获扣除 20、剩余保留）；
    ``today_points`` / ``today_farm_xp`` 是当日计数，跨自然日清零（读取时按
    日期比对惰性重置，不回写历史）。
    """

    __tablename__ = "vocab_farm_plot"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_vocab_farm_plot_user"),
        Index(
            "ix_vocab_farm_plot_tenant_last_harvested_at",
            "tenant_id",
            "last_harvested_at",
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 跨班连续键：登录账号（不是某一班的 student 档案）
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )

    # 当前地块成长点数（收获后扣除成熟阈值，剩余保留）
    growth_points: int = Field(default=0, ge=0)
    # 今日已计成长点数（每日 30 上限）
    today_points: int = Field(default=0, ge=0)
    last_points_date: date | None = Field(default=None, sa_type=Date)
    # 今日已发放的农场 XP（每日 10 上限）
    today_farm_xp: int = Field(default=0, ge=0)
    last_farm_xp_date: date | None = Field(default=None, sa_type=Date)
    # 累计收获次数（农场徽章口径）与最近一次收获留痕
    harvest_count: int = Field(default=0, ge=0)
    last_harvested_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── 接口 schema（非表）─────────────────────────────────────────────


class FarmBadgePublic(SQLModel):
    """徽章展示项：带来源标注（只读，不参与任何结算口径）。"""

    key: str
    label: str
    description: str
    awarded_at: datetime | None = None
    # 专注农场 / 课堂档案·每日计划
    source: str = BADGE_SOURCE_CLASSROOM


class FarmView(SQLModel):
    """GET /classes/{code}/vocabulary/student/farm。"""

    # 0..3，对应 STAGE_THRESHOLDS 的四阶段
    stage: int
    stage_thresholds: list[int]
    growth_points: int
    # 距成熟还差几点；已成熟为 0
    points_to_mature: int
    ready_to_harvest: bool
    today_points: int
    daily_growth_cap: int
    # 既有账本口径：当前课堂档案的 XP 余额与连胜（只读，农场不改写）
    xp: int = 0
    streak_days: int = 0
    harvest_count: int = 0
    today_farm_xp: int = 0
    farm_xp_daily_cap: int = FARM_XP_DAILY_CAP
    # 可收获 = 已成熟且今日农场 XP 未达上限
    can_harvest: bool = False
    badges: list[FarmBadgePublic] = []
    last_harvested_at: datetime | None = None


class FarmHarvestResult(SQLModel):
    """POST .../farm/harvest 回执：收获入账后的地块与账本快照。"""

    harvested: bool
    xp_gained: int = 0
    xp: int = 0
    growth_points: int = 0
    stage: int = 0
    harvest_count: int = 0
    # 本次新拿到的徽章 key（既有账本落库）
    newly_awarded: list[str] = []
    badges: list[FarmBadgePublic] = []
