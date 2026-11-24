"""班级掌握度纯函数单测：分段边界、零作答、正确率取整。

分段口径：<60% low；60–85%（含 60 与 85）mid；>85% high；无首答 no_data。
零作答正确率为 None，界面显示 –，不画成 0%。
"""

import pytest

from app.services.vocabulary_mastery import first_try_accuracy, mastery_band


@pytest.mark.parametrize(
    ("correct", "answered", "expected_pct", "expected_band"),
    [
        # 边界点：59 偏弱 / 60 中段 / 85 中段 / 86 较稳
        (59, 100, 59, "low"),
        (60, 100, 60, "mid"),
        (85, 100, 85, "mid"),
        (86, 100, 86, "high"),
        # 小分母等价边界
        (3, 5, 60, "mid"),
        (2, 5, 40, "low"),
        (17, 20, 85, "mid"),
        (18, 20, 90, "high"),
        # 全对 / 全错
        (5, 5, 100, "high"),
        (0, 5, 0, "low"),
    ],
)
def test_mastery_band_boundaries(
    correct: int,
    answered: int,
    expected_pct: int,
    expected_band: str,
) -> None:
    pct, band = mastery_band(correct, answered)
    assert pct == expected_pct
    assert band == expected_band


def test_mastery_band_no_data_when_zero_answers() -> None:
    pct, band = mastery_band(0, 0)
    assert pct is None
    assert band == "no_data"


def test_first_try_accuracy_rounds_and_none_when_empty() -> None:
    assert first_try_accuracy(1, 3) == 33  # 33.33 → 33
    assert first_try_accuracy(2, 3) == 67  # 66.67 → 67
    assert first_try_accuracy(0, 0) is None
