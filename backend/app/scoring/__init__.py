"""评分包：引擎抽象 + 实现 + worker。路由只通过 base/asr/worker 的公开名使用。"""

from app.scoring.base import AsrProvider, ReadAloudScores, ScoringError
from app.scoring.heuristic import score_read_aloud

__all__ = [
    "AsrProvider",
    "ReadAloudScores",
    "ScoringError",
    "score_read_aloud",
]
