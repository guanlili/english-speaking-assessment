"""粗分档自适应小测：纯逻辑规则单测（不依赖数据库）。

覆盖：五级 → 四档映射、答对升/答错降与边界钳制、建议档收敛规则、档位兜底顺序。
"""

import pytest

from app.models import (
    PLACEMENT_BAND_ORDER,
    PLACEMENT_PASS_CORRECT,
)
from app.services import vocab_placement


def test_level_to_band_maps_four_bands() -> None:
    assert vocab_placement.level_to_band("KET") == "KET"
    assert vocab_placement.level_to_band("PET") == "PET"
    assert vocab_placement.level_to_band("CET4") == "CET4"
    # 顶档合并：ACADEMIC 与 IELTS_TOEFL 同归 ADVANCED
    assert vocab_placement.level_to_band("ACADEMIC") == "ADVANCED"
    assert vocab_placement.level_to_band("IELTS_TOEFL") == "ADVANCED"


def test_level_to_band_unknown_or_none_excluded() -> None:
    assert vocab_placement.level_to_band(None) is None
    assert vocab_placement.level_to_band("UNKNOWN") is None


def test_next_band_climbs_on_correct_and_drops_on_wrong() -> None:
    assert vocab_placement.next_band("PET", True) == "CET4"
    assert vocab_placement.next_band("PET", False) == "KET"
    assert vocab_placement.next_band("CET4", True) == "ADVANCED"
    assert vocab_placement.next_band("CET4", False) == "PET"


def test_next_band_clamped_at_bottom_and_top() -> None:
    # 底档答错不再下探
    assert vocab_placement.next_band("KET", False) == "KET"
    # 顶档答对不再上探
    assert vocab_placement.next_band("ADVANCED", True) == "ADVANCED"


def test_recommend_band_highest_with_two_or_more_correct() -> None:
    band_correct = {"KET": 3, "PET": 2, "CET4": 1, "ADVANCED": 0}
    # PET 达到 2 次、CET4 未达到 → 建议 PET
    assert vocab_placement.recommend_band(band_correct) == "PET"

    band_correct["CET4"] = 2
    assert vocab_placement.recommend_band(band_correct) == "CET4"

    band_correct["ADVANCED"] = PLACEMENT_PASS_CORRECT
    assert vocab_placement.recommend_band(band_correct) == "ADVANCED"


def test_recommend_band_falls_back_to_ket_when_none_passes() -> None:
    # 每档都不足 2 次正确 → 兜底 KET（不给出高于证据的建议）
    band_correct = {"KET": 1, "PET": 1, "CET4": 0, "ADVANCED": 0}
    assert vocab_placement.recommend_band(band_correct) == "KET"
    assert vocab_placement.recommend_band({}) == "KET"


def test_band_preference_starts_current_then_nearest_neighbors() -> None:
    assert vocab_placement._band_preference("PET") == ["PET", "KET", "CET4", "ADVANCED"]
    assert vocab_placement._band_preference("KET") == ["KET", "PET", "CET4", "ADVANCED"]
    assert vocab_placement._band_preference("ADVANCED") == [
        "ADVANCED",
        "CET4",
        "PET",
        "KET",
    ]


@pytest.mark.parametrize(
    "start,correct,expected",
    [
        ("KET", True, "PET"),
        ("PET", True, "CET4"),
        ("CET4", True, "ADVANCED"),
        ("ADVANCED", False, "CET4"),
        ("CET4", False, "PET"),
        ("PET", False, "KET"),
    ],
)
def test_next_band_step_table(start: str, correct: bool, expected: str) -> None:
    assert vocab_placement.next_band(start, correct) == expected
    assert expected in PLACEMENT_BAND_ORDER
