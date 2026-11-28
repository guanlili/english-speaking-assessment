"""学生词汇坐标（0%–100% 贯通进度）的 API schema 与口径常量（#616）。

坐标是学习进度，不是雅思/托福分数、不是能力认证；百分比 = 已掌握词数 ÷
当前可练基准词表词数，两个数都会随接口下发，老师可以自己复算。
"""

from sqlmodel import SQLModel

# 台阶数量默认值（可配；教研口径未定前不把 12–18 写死，也不对外承诺）
COORDINATE_STEP_COUNT_DEFAULT = 12
COORDINATE_STEP_COUNT_MIN = 2
COORDINATE_STEP_COUNT_MAX = 40
COORDINATE_RULE_VERSION = "coord-v1"


class VocabularyCoordinate(SQLModel):
    """学生词汇坐标：一次只读计算的结果（不写学生等级字段，不改历史）。

    measured=False 表示「未测」（还没有任何独立首答，或当前没有可练词库），
    此时 percent / 台阶字段一律为 None，前端显示未测，不折算成 0%。
    """

    classroom_code: str
    measured: bool = False
    # 0–100 整数；None = 未测
    percent: int | None = None
    # 分子：已掌握词数（首答答对 ∪ FSRS review），按当前基准词表口径取交集
    mastered_word_count: int = 0
    # 分母：当前可练基准词表词数（active 公共库 + 本班库内 approved active 词条）
    basis_word_count: int = 0
    # 明细来源（透明可复算）：首答答对数 / FSRS review 数（已去重，不重叠计数）
    mastered_first_try_count: int = 0
    mastered_fsrs_count: int = 0
    # 本人独立首答过的词条数（测过没测过的判定依据）
    answered_first_count: int = 0
    # 台阶：等宽百分比区间，左闭右开，100% 归最后一阶
    steps_total: int = COORDINATE_STEP_COUNT_DEFAULT
    step_index: int | None = None
    step_start_percent: int | None = None
    step_end_percent: int | None = None
    # 距本阶终点还差多少词 / 到 100% 还差多少词（未测时后者仍可算）
    words_to_next_step: int | None = None
    words_to_goal: int | None = None
    rule_version: str = COORDINATE_RULE_VERSION
