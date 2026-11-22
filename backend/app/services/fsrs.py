"""FSRS-4.5 间隔重复调度核心（纯函数、确定性、时钟可注入）。

算法来源：open-spaced-repetition/FSRS（ts-fsrs / fsrs-rs 参考实现），
参数版本 **FSRS-4.5**，17 个默认权重 ``w[0..16]`` 见 :data:`DEFAULT_WEIGHTS`。
本模块只移植调度核心——初始稳定性/难度、复习后稳定性与难度更新、下次到期
时间——不做参考实现里的随机区间 fuzz（确定性：同输入、同时钟必然同输出），
也不持有数据库会话或任何网络调用。

评分口径（本平台只保留两档，接入层 ``services/vocabulary_review.py``）：

- ``again``（=1）：独立首答判错；``good``（=3）：独立首答对。
- 不使用 ``hard`` / ``easy``：练习反馈只有对错两档，不允许学生自评记忆强度。
- 重试（attempt_no>1）不进入调度：学习状态只由独立首答证据驱动，重试不升级、
  也不降级状态。

公式（FSRS-4.5）：

新卡：
    S₀ = w[rating-1]                     # Again w[0] / Good w[2]
    D₀ = clamp(w[4] - exp(w[5]*(rating-1)), 1, 10)

复习卡（t = 距上次复习的天数，R = exp(-t/S)）：
    D' = clamp(D - w[6]*(rating-3), 1, 10)
    Again： S' = max(0.1, S * exp(-w[11]))            # 遗忘后稳定性回落
    其余：  S' = S * (1 + exp(w[7]) * (10-D')/9 * R^w[8] * (1-R)^w[9]
                       * exp(w[15]*(rating-3)))
    下次到期 = now + S' 天；展示间隔 interval_days = max(1, round(S'))
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# ── 评分档（FSRS 原始 1..4；本平台只用 again / good）─────────────────

RATING_AGAIN = "again"
RATING_GOOD = "good"

_RATING_INDEX: dict[str, int] = {RATING_AGAIN: 1, RATING_GOOD: 3}

# ── FSRS-4.5 默认权重（标准参考值，未做本平台数据拟合）────────────────
# 顺序对应 ts-fsrs 默认 w：0..3 新卡稳定性（Again/Hard/Good/Easy），
# 4 新卡难度截距，5 难度评分系数，6 难度更新步长，7 难度—稳定系数，
# 8 可提取性指数，9 遗忘指数，11 遗忘稳定性回落系数，15 评分调节系数；
# 10/12/13/14/16 为 FSRS 后续版本扩展位，4.5 两档评分下保留不用。
DEFAULT_WEIGHTS: tuple[float, ...] = (
    0.4072,  # w0  Again 初始稳定性（天）
    1.189,  # w1  Hard  初始稳定性（本平台不用）
    3.1362,  # w2  Good  初始稳定性（天）
    1.0844,  # w3  Easy  初始稳定性（本平台不用）
    2.1226,  # w4  新卡难度截距
    1.9629,  # w5  新卡难度评分系数
    0.0947,  # w6  难度更新步长
    1.7215,  # w7  难度—稳定系数
    0.5316,  # w8  可提取性指数 R^w8
    1.0655,  # w9  遗忘指数 (1-R)^w9
    0.0234,  # w10 预留（FSRS-5+）
    1.61,  # w11 遗忘稳定性回落系数
    0.1544,  # w12 预留
    1.2467,  # w13 预留
    0.2118,  # w14 预留
    0.2063,  # w15 评分调节系数 exp(w15*(rating-3))
    0.3498,  # w16 预留
)

_MIN_STABILITY = 0.1  # 天：遗忘后稳定性下限，防止到期时间无限提前
_MIN_DIFFICULTY = 1.0
_MAX_DIFFICULTY = 10.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _state_for(reps: int) -> str:
    """状态派生：new=尚未复习；learning=前两次复习内；review=已建立长期记忆。"""
    if reps <= 0:
        return "new"
    if reps < 2:
        return "learning"
    return "review"


@dataclass(frozen=True)
class FSRSCard:
    """一张词条某能力维度的调度状态（不可变；更新返回新实例）。"""

    stability: float  # 记忆稳定性（天），FSRS 主调度量
    difficulty: float  # 难度 1..10
    reps: int  # 累计复习次数（独立首答口径）
    lapses: int  # 累计遗忘（again）次数
    state: str  # new / learning / review
    due_at: datetime  # 下次到期时间（服务器时区）
    last_review_at: datetime | None  # 上次复习时间；新卡为 None
    last_rating: str | None  # 上次评分 again / good；新卡为 None
    interval_days: int  # 当前展示间隔（天，可解释字段）


def _interval_days(stability: float) -> int:
    return max(1, round(stability))


def rate_new(
    rating: str, now: datetime, weights: tuple[float, ...] = DEFAULT_WEIGHTS
) -> FSRSCard:
    """新卡第一次评分：初始化稳定性、难度与到期时间。

    ``now`` 由调用方注入（服务端时间），模块内部不读系统时钟，保证可测试、
    可复算。``rating`` 只接受 again / good。
    """
    if rating not in _RATING_INDEX:
        raise ValueError(f"不支持的 FSRS 评分：{rating}")
    rating_index = _RATING_INDEX[rating]
    stability = max(_MIN_STABILITY, weights[rating_index - 1])
    difficulty = _clamp(
        weights[4] - _exp(weights[5] * (rating_index - 1)),
        _MIN_DIFFICULTY,
        _MAX_DIFFICULTY,
    )
    due_at = now + timedelta(days=stability)
    return FSRSCard(
        stability=stability,
        difficulty=difficulty,
        reps=1,
        lapses=1 if rating == RATING_AGAIN else 0,
        state=_state_for(1),
        due_at=due_at,
        last_review_at=now,
        last_rating=rating,
        interval_days=_interval_days(stability),
    )


def rate_review(
    card: FSRSCard,
    rating: str,
    now: datetime,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
) -> FSRSCard:
    """已存在卡片复习评分：按距上次复习的经过时间更新稳定性/难度与到期时间。

    纯函数：不修改入参卡片；``now`` 注入，经过时间由 ``last_review_at`` 推算。
    """
    if rating not in _RATING_INDEX:
        raise ValueError(f"不支持的 FSRS 评分：{rating}")
    rating_index = _RATING_INDEX[rating]
    if card.last_review_at is None:
        raise ValueError("复习卡必须有 last_review_at；新卡请走 rate_new")

    elapsed_days = max(0.0, (now - card.last_review_at).total_seconds() / 86_400.0)
    difficulty = _clamp(
        card.difficulty - weights[6] * (rating_index - 3),
        _MIN_DIFFICULTY,
        _MAX_DIFFICULTY,
    )
    if rating == RATING_AGAIN:
        stability = max(_MIN_STABILITY, card.stability * _exp(-weights[11]))
        lapses = card.lapses + 1
    else:
        retrievability = (
            _exp(-elapsed_days / card.stability) if card.stability > 0 else 0.0
        )
        stability = card.stability * (
            1.0
            + _exp(weights[7])
            * (_MAX_DIFFICULTY - difficulty)
            / 9.0
            * retrievability ** weights[8]
            * (1.0 - retrievability) ** weights[9]
            * _exp(weights[15] * (rating_index - 3))
        )
        stability = max(_MIN_STABILITY, stability)
        lapses = card.lapses

    due_at = now + timedelta(days=stability)
    reps = card.reps + 1
    return FSRSCard(
        stability=stability,
        difficulty=difficulty,
        reps=reps,
        lapses=lapses,
        state=_state_for(reps),
        due_at=due_at,
        last_review_at=now,
        last_rating=rating,
        interval_days=_interval_days(stability),
    )


def overdue_days(due_at: datetime, now: datetime) -> int:
    """逾期天数（不足一天按 0 计；未到期为 0）。"""
    return max(0, int((now - due_at).total_seconds() // 86_400))


def _exp(value: float) -> float:
    """指数计算，避免极小/极大输入溢出（FSRS 权重范围内不会触发）。"""
    import math

    return math.exp(_clamp(value, -60.0, 60.0))


def utc_now() -> datetime:
    """模块默认时钟（仅接入层取服务端当前时间用；测试一律注入 now）。"""
    return datetime.now(UTC)
