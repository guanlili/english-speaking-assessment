"""专注农场域逻辑：成长计数、成熟判定、收获入账与农场徽章。

边界（设计稿 `docs/vocabulary-pk-farm-design-20261122.md` §4）：

- 成长只由有效首答事件驱动（调用方已过滤 quiz 与重试 attempt_no>1）；
  切屏/空闲不产生成长，也不宣称能证明专注。
- 地块按 ``user_id`` 跨班连续；历史班级作答与快照不被迁移或重写。
- 收获 XP 写当前课堂档案 ``student.xp``（既有账本），不新造并行积分；
  streak 不由本模块推进或重置；徽章落既有 ``student_badge`` 表。
"""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    BADGE_FARM_FIRST_HARVEST,
    BADGE_FARM_HARVEST_7,
    BADGE_SOURCE_CLASSROOM,
    BADGE_SOURCE_FARM,
    FARM_XP_DAILY_CAP,
    GROWTH_DAILY_CAP,
    GROWTH_PER_EVENT,
    HARVEST_COUNT_BADGE,
    HARVEST_XP,
    MATURE_POINTS,
    STAGE_THRESHOLDS,
    FarmBadgePublic,
    FarmHarvestResult,
    FarmView,
    Student,
    StudentBadge,
    VocabFarmPlot,
)
from app.scoring.gamification import BADGE_BY_KEY, award_xp, student_badges


def _today() -> date:
    """练习日切分（PRACTICE_TZ）：与 FSRS 复习队列同一自然日口径。"""
    return datetime.now(ZoneInfo(settings.PRACTICE_TZ)).date()


def _get_plot(session: Session, user_id: uuid.UUID) -> VocabFarmPlot | None:
    return session.exec(
        select(VocabFarmPlot).where(VocabFarmPlot.user_id == user_id)  # type: ignore[arg-type]
    ).first()


def _get_or_create_plot(session: Session, user_id: uuid.UUID) -> VocabFarmPlot:
    plot = _get_plot(session, user_id)
    if plot is None:
        plot = VocabFarmPlot(user_id=user_id)
        session.add(plot)
        session.commit()
        session.refresh(plot)
    return plot


def stage_of(growth_points: int) -> int:
    """四阶段派生：0 种子 / 1 发芽 / 2 生长 / 3 成熟。"""
    if growth_points >= STAGE_THRESHOLDS[3]:
        return 3
    if growth_points >= STAGE_THRESHOLDS[2]:
        return 2
    if growth_points >= STAGE_THRESHOLDS[1]:
        return 1
    return 0


def _today_points(plot: VocabFarmPlot, today: date) -> int:
    return plot.today_points if plot.last_points_date == today else 0


def _today_farm_xp(plot: VocabFarmPlot, today: date) -> int:
    return plot.today_farm_xp if plot.last_farm_xp_date == today else 0


def record_valid_first_answer(session: Session, *, user_id: uuid.UUID) -> bool:
    """一条有效首答 +1 成长点；当日达 30 上限不再计。返回是否入账。

    调用方保证：非测验轮、``attempt_no == 1``；重试与 quiz 不进本入口。
    """
    plot = _get_or_create_plot(session, user_id)
    today = _today()
    if plot.last_points_date != today:
        plot.today_points = 0
        plot.last_points_date = today
    if plot.today_points >= GROWTH_DAILY_CAP:
        session.add(plot)
        session.commit()
        return False
    plot.today_points += GROWTH_PER_EVENT
    plot.growth_points += GROWTH_PER_EVENT
    plot.updated_at = datetime.now(UTC)
    session.add(plot)
    session.commit()
    return True


def _badge_publics(session: Session, student_id: uuid.UUID) -> list[FarmBadgePublic]:
    rows = student_badges(session, student_id)
    publics: list[FarmBadgePublic] = []
    for badge in rows:
        defn = BADGE_BY_KEY.get(badge.badge_key)
        source = (
            BADGE_SOURCE_FARM
            if badge.badge_key.startswith("farm_")
            else BADGE_SOURCE_CLASSROOM
        )
        publics.append(
            FarmBadgePublic(
                key=badge.badge_key,
                label=defn.label if defn else badge.badge_key,
                description=defn.description if defn else "",
                awarded_at=badge.awarded_at,
                source=source,
            )
        )
    return publics


def plot_view(session: Session, *, student: Student, user_id: uuid.UUID) -> FarmView:
    """农场只读视图：地块阶段、今日有效练习、XP/连胜（只读）与徽章来源。"""
    plot = _get_or_create_plot(session, user_id)
    today = _today()
    today_points = _today_points(plot, today)
    today_farm_xp = _today_farm_xp(plot, today)
    ready = plot.growth_points >= MATURE_POINTS
    return FarmView(
        stage=stage_of(plot.growth_points),
        stage_thresholds=list(STAGE_THRESHOLDS),
        growth_points=plot.growth_points,
        points_to_mature=max(0, MATURE_POINTS - plot.growth_points),
        ready_to_harvest=ready,
        today_points=today_points,
        daily_growth_cap=GROWTH_DAILY_CAP,
        xp=student.xp or 0,
        streak_days=student.streak_days or 0,
        harvest_count=plot.harvest_count,
        today_farm_xp=today_farm_xp,
        farm_xp_daily_cap=FARM_XP_DAILY_CAP,
        can_harvest=ready and today_farm_xp < FARM_XP_DAILY_CAP,
        badges=_badge_publics(session, student.id),
        last_harvested_at=plot.last_harvested_at,
    )


def harvest(
    session: Session, *, student: Student, user_id: uuid.UUID
) -> FarmHarvestResult:
    """成熟地块收获：+10 XP 入既有 ``student.xp``，扣除 20 点、剩余保留。

    幂等口径：未成熟 → 422；今日农场 XP 已达上限 → 422 并说明；
    收获后点数回落至阈值以下，重复请求不会二次入账。streak 不变。
    """
    plot = _get_or_create_plot(session, user_id)
    today = _today()
    today_farm_xp = _today_farm_xp(plot, today)

    if plot.growth_points < MATURE_POINTS:
        raise HTTPException(status_code=422, detail="作物还没成熟，暂时不能收获")
    if today_farm_xp >= FARM_XP_DAILY_CAP:
        raise HTTPException(
            status_code=422,
            detail="今日农场 XP 已达上限，明天再来收获",
        )

    # XP 入账既有课堂档案余额；source 归因到农场，不另立账本
    award_xp(session, student, HARVEST_XP, source="vocab_farm")

    plot.growth_points -= MATURE_POINTS
    plot.today_farm_xp = today_farm_xp + HARVEST_XP
    plot.last_farm_xp_date = today
    plot.harvest_count += 1
    plot.last_harvested_at = datetime.now(UTC)
    plot.updated_at = plot.last_harvested_at
    session.add(plot)

    owned = set(
        session.exec(
            select(StudentBadge.badge_key).where(
                StudentBadge.student_id == student.id  # type: ignore[arg-type]
            )
        ).all()
    )
    newly_awarded: list[str] = []
    candidates = (
        (BADGE_FARM_FIRST_HARVEST, True),
        (BADGE_FARM_HARVEST_7, plot.harvest_count >= HARVEST_COUNT_BADGE),
    )
    for key, hit in candidates:
        if hit and key not in owned:
            session.add(StudentBadge(student_id=student.id, badge_key=key))
            newly_awarded.append(key)

    session.commit()
    session.refresh(plot)
    session.refresh(student)

    return FarmHarvestResult(
        harvested=True,
        xp_gained=HARVEST_XP,
        xp=student.xp or 0,
        growth_points=plot.growth_points,
        stage=stage_of(plot.growth_points),
        harvest_count=plot.harvest_count,
        newly_awarded=newly_awarded,
        badges=_badge_publics(session, student.id),
    )
