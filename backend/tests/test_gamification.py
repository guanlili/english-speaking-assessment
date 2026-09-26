"""激励层单元测试：星级分档、连胜推进。"""

from datetime import date, timedelta

from app.scoring.gamification import advance_streak, compute_stars


def test_stars_thresholds() -> None:
    assert compute_stars([90, 88]) == 3
    assert compute_stars([75, 70]) == 2
    assert compute_stars([60, 40]) == 1
    assert compute_stars([]) == 1  # 完成保底


def test_advance_streak_rules() -> None:
    today = date(2026, 9, 26)
    assert advance_streak(None, 0, today) == 1  # 首次
    assert advance_streak(today - timedelta(days=1), 3, today) == 4  # 连续
    assert advance_streak(today - timedelta(days=2), 5, today) == 1  # 断档重置
    assert advance_streak(today, 3, today) == 3  # 当天已结算不变
