"""FSRS-4.5 调度核心单元测试：确定性、评分映射、时钟注入、边界与幂等。

不接数据库/网络；全部用注入的固定时钟，同输入必须同输出（确定性锁死）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import fsrs

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def test_rate_new_is_deterministic() -> None:
    """同评分同时钟 → 稳定性/难度/到期时间/间隔完全一致。"""
    first = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    second = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    assert first == second


def test_rate_new_good_stability_larger_than_again() -> None:
    """首答对（good）初始稳定性高于首答错（again）；难度均落在 1..10。"""
    good = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    again = fsrs.rate_new(fsrs.RATING_AGAIN, NOW)
    assert good.stability > again.stability
    assert 1.0 <= good.difficulty <= 10.0
    assert 1.0 <= again.difficulty <= 10.0
    assert good.reps == 1
    assert again.lapses == 1
    assert good.lapses == 0


def test_due_at_derived_from_injected_clock() -> None:
    """到期时间跟随注入时钟；换时钟结果整体平移，不读系统墙钟。"""
    later = NOW + timedelta(days=3)
    card = fsrs.rate_new(fsrs.RATING_GOOD, later)
    assert card.due_at > later
    assert card.last_review_at == later


def test_review_good_grows_stability_and_keeps_lapses() -> None:
    """复习答对：稳定性增长、遗忘次数不变、复习次数 +1。"""
    card = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    future = NOW + timedelta(days=card.interval_days)
    reviewed = fsrs.rate_review(card, fsrs.RATING_GOOD, future)
    assert reviewed.stability > card.stability
    assert reviewed.lapses == card.lapses
    assert reviewed.reps == card.reps + 1
    assert reviewed.due_at > future


def test_review_again_lapses_and_drops_stability() -> None:
    """复习答错：遗忘次数 +1、稳定性回落、难度不变差于上限。"""
    card = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    future = NOW + timedelta(days=card.interval_days)
    reviewed = fsrs.rate_review(card, fsrs.RATING_AGAIN, future)
    assert reviewed.lapses == card.lapses + 1
    assert reviewed.stability < card.stability
    assert 1.0 <= reviewed.difficulty <= 10.0


def test_difficulty_is_clamped_to_range() -> None:
    """多次 again 后难度不低于 1；多次 good 后不高于 10。"""
    card = fsrs.rate_new(fsrs.RATING_AGAIN, NOW)
    for _ in range(6):
        card = fsrs.rate_review(card, fsrs.RATING_AGAIN, NOW + timedelta(days=1))
        assert card.difficulty >= 1.0
    easy = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    for _ in range(6):
        easy = fsrs.rate_review(easy, fsrs.RATING_GOOD, NOW + timedelta(days=1))
        assert easy.difficulty <= 10.0


def test_overdue_days_boundaries() -> None:
    assert fsrs.overdue_days(NOW + timedelta(hours=6), NOW) == 0
    assert fsrs.overdue_days(NOW, NOW) == 0
    assert fsrs.overdue_days(NOW - timedelta(days=2, hours=1), NOW) == 2
    assert fsrs.overdue_days(NOW - timedelta(hours=20), NOW) == 0


def test_review_requires_last_review_at() -> None:
    """构造缺 last_review_at 的卡片走复习口径必须报错（不能当新卡静默处理）。"""
    card = fsrs.FSRSCard(
        stability=2.0,
        difficulty=5.0,
        reps=1,
        lapses=0,
        state="learning",
        due_at=NOW,
        last_review_at=None,
        last_rating="good",
        interval_days=2,
    )
    with pytest.raises(ValueError, match="last_review_at"):
        fsrs.rate_review(card, fsrs.RATING_GOOD, NOW)


def test_invalid_rating_rejected() -> None:
    with pytest.raises(ValueError, match="不支持的 FSRS 评分"):
        fsrs.rate_new("easy", NOW)
    card = fsrs.rate_new(fsrs.RATING_GOOD, NOW)
    with pytest.raises(ValueError, match="不支持的 FSRS 评分"):
        fsrs.rate_review(card, "hard", NOW)


def test_state_derivation() -> None:
    new = fsrs.rate_new(fsrs.RATING_AGAIN, NOW)
    assert new.state == "learning"
    second = fsrs.rate_review(new, fsrs.RATING_GOOD, NOW + timedelta(days=1))
    assert second.state == "review"
