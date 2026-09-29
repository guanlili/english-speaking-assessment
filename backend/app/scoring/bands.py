"""练习档位规则（PRD §6）。

三档：A2（低）/ B1（中）/ B2（高），不按考试原题难度。
抽题规则：第一节默认中档；跟读完整度 ≥80 且流利度达标升一档；
明显读不完（完整度 <50）降一档。调整不告诉学生，只换题。
"""

BAND_LOW = "A2"
BAND_MID = "B1"
BAND_HIGH = "B2"
BAND_ORDER = [BAND_LOW, BAND_MID, BAND_HIGH]
DEFAULT_BAND = BAND_MID

# 升档：完整度 ≥80 且流利度 ≥60；降档：完整度 <50（US-05 验收口径）
UP_COMPLETENESS = 80
UP_FLUENCY = 60
DOWN_COMPLETENESS = 50


def adjust_band(avg_completeness: float, avg_fluency: float, current: str) -> str:
    if current not in BAND_ORDER:
        return DEFAULT_BAND
    if avg_completeness < DOWN_COMPLETENESS:
        return BAND_ORDER[max(0, BAND_ORDER.index(current) - 1)]
    if avg_completeness >= UP_COMPLETENESS and avg_fluency >= UP_FLUENCY:
        return BAND_ORDER[min(len(BAND_ORDER) - 1, BAND_ORDER.index(current) + 1)]
    return current
