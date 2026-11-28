"""学生词汇坐标（0%–100% 贯通进度 + 台阶）的纯函数单测（#616）。

只测换算本身：分母为 0、未测不折算 0%、四舍五入、台阶左闭右开、
100% 归最后一阶、台阶数量可配。
"""

from app.models import COORDINATE_STEP_COUNT_DEFAULT
from app.services.vocab_coordinate import ceil_count, compute_coordinate


def _calc(*, answered: int, first: int, fsrs: int = 0, basis: int, steps: int = 12):
    return compute_coordinate(
        answered_first_count=answered,
        mastered_first_try_count=first,
        mastered_fsrs_count=fsrs,
        basis_word_count=basis,
        steps=steps,
    )


def test_no_basis_is_unmeasured() -> None:
    """还没有可练词库：未测，百分比与台阶都为 None，也不折算 0%。"""
    snap = _calc(answered=0, first=0, basis=0)
    assert snap.measured is False
    assert snap.percent is None
    assert snap.step_index is None
    assert snap.words_to_goal is None


def test_no_answers_is_unmeasured_not_zero() -> None:
    """有词库但一条首答都没有：未测，不显示 0%。"""
    snap = _calc(answered=0, first=0, basis=100)
    assert snap.measured is False
    assert snap.percent is None
    assert snap.words_to_goal == 100


def test_zero_percent_and_first_step() -> None:
    """测过但一个没掌握：百分比 0，落在第 1 阶。"""
    snap = _calc(answered=3, first=0, basis=100)
    assert snap.measured is True
    assert snap.percent == 0
    assert snap.step_index == 1
    assert snap.step_start_percent == 0
    assert snap.step_end_percent == 8  # int(100/12)
    assert snap.words_to_next_step == 8  # ceil(100*8/100)=8


def test_percent_rounding_and_union_dedup() -> None:
    """四舍五入到整数；FSRS 命中但首答没对也算掌握（调用方保证去重）。"""
    snap = _calc(answered=10, first=40, fsrs=3, basis=100)
    assert snap.mastered_word_count == 43
    assert snap.percent == 43


def test_mastered_capped_by_basis() -> None:
    """分子不会超过分母（词表缩小后不出现 120%）。"""
    snap = _calc(answered=10, first=50, fsrs=20, basis=50)
    assert snap.mastered_word_count == 50
    assert snap.percent == 100


def test_hundred_percent_last_step() -> None:
    """100% 归最后一阶，且没有「还差多少」的余量。"""
    snap = _calc(answered=10, first=10, basis=10)
    assert snap.percent == 100
    assert snap.step_index == COORDINATE_STEP_COUNT_DEFAULT
    assert snap.step_start_percent == 91  # int(11*100/12)=91
    assert snap.step_end_percent == 100
    assert snap.words_to_next_step == 0
    assert snap.words_to_goal == 0


def test_steps_configurable() -> None:
    """台阶数量可配：同样 50% 在 4 阶口径下落在第 3 阶。"""
    snap = _calc(answered=10, first=5, basis=10, steps=4)
    assert snap.steps_total == 4
    assert snap.step_index == 3
    assert snap.step_start_percent == 50
    assert snap.step_end_percent == 75
    assert snap.words_to_next_step == 3  # ceil(10*75/100)=8, 8-5=3


def test_steps_clamped() -> None:
    """台阶数量越界按上下限夹住，不因前端传 0/999 崩掉。"""
    assert _calc(answered=1, first=0, basis=10, steps=0).steps_total == 2
    assert _calc(answered=1, first=0, basis=10, steps=999).steps_total == 40


def test_ceil_count() -> None:
    """百分比阈值 → 词数向上取整，保证「达到该阶终点」可算。"""
    assert ceil_count(0, 50) == 0
    assert ceil_count(10, 50) == 5
    assert ceil_count(3, 50) == 2  # 1.5 → 2
