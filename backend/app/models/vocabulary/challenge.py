"""每日挑战的接口模型（#618）。"""

from __future__ import annotations

import uuid
from datetime import date

from sqlmodel import SQLModel


class VocabularyChallengeBlock(SQLModel):
    """挑战包里的一块练习（维度 + 玩法 + 题量）。"""

    dimension: str
    key: str
    item_count: int


class VocabularyDailyChallenge(SQLModel):
    """学生端「今日挑战」展示：配置 + 完成状态，不暴露答案。"""

    classroom_code: str
    date: date
    degraded: bool
    reason: str | None = None
    blocks: list[VocabularyChallengeBlock]
    total_items: int
    completed: bool
    session_id: uuid.UUID | None = None


class VocabularyChallengeCreated(SQLModel):
    """开挑战轮返回会话 ID，前端复用自主练习作答页。"""

    session_id: uuid.UUID
    total_items: int


class VocabularyChallengeParticipation(SQLModel):
    """教师端只读参与情况（今天开过 / 已完成的人数）。"""

    date: date
    started_count: int
    completed_count: int
