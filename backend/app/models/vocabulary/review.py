"""词汇 FSRS 复习状态：学生学习档案（与首答统计完全独立的第二套口径）。

设计不变量（对应 issue #517 第二批）：

- **首答仍是统计唯一口径**：本表只存 FSRS 调度所需的学习状态，不回填、不改写
  ``VocabularyAnswer`` 与教师结果统计；错词本历史错误次数只增不减，本表的
  「待复习」状态不替换、不折算旧计数。
- **跨班连续性**：状态按登录账号 ``user_id`` 汇总（同一账号换班后队列继续
  可用）；历史 session 仍保留原 ``classroom_id``，不做迁移或重写。
- **认读 / 拼写分离**：同一词条的认读（选择题类）与拼写（填空/词根/看义
  拼写）各有一行状态，到期时间、复习次数互不影响。
- **快照不可变**：队列读取词条当前内容用于出题展示；历史 session 的
  ``snapshot_items`` 永不被本表改动。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    _tenant_id_field,
    get_datetime_utc,
)

# 能力维度：recognition = 认读（选择题类）；spelling = 拼写（输入词形类）
CAPABILITY_RECOGNITION = "recognition"
CAPABILITY_SPELLING = "spelling"
REVIEW_CAPABILITIES = (CAPABILITY_RECOGNITION, CAPABILITY_SPELLING)

# 调度状态：new=尚未复习；learning=前两次复习内；review=已建立长期记忆
REVIEW_STATE_NEW = "new"
REVIEW_STATE_LEARNING = "learning"
REVIEW_STATE_REVIEW = "review"


class VocabularyReviewState(SQLModel, table=True):
    """一个账号 × 一个词条 × 一种能力维度 的 FSRS 调度状态。"""

    __tablename__ = "vocabulary_review_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "word_id", "capability", name="uq_vocab_review_state_card"
        ),
        Index("ix_vocab_review_state_due", "due_at"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 跨班汇总键：登录账号（不是某一班的 student 档案）
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # 词条标识（无外键：归档词条的历史状态保留，与 VocabularyAnswer.word_id 同口径）
    word_id: uuid.UUID = Field(index=True)
    capability: str = Field(max_length=16, index=True)

    state: str = Field(default=REVIEW_STATE_NEW, max_length=16)
    # FSRS 主调度量：稳定性（天）与难度 1..10
    stability: float = Field(default=0.0)
    difficulty: float = Field(default=5.0)
    reps: int = Field(default=0, ge=0)
    lapses: int = Field(default=0, ge=0)
    # 当前展示间隔（天，可解释字段）；新卡为 None
    interval_days: int | None = Field(default=None, ge=0)
    due_at: datetime = Field(sa_type=DateTime(timezone=True))  # type: ignore
    last_review_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 上次评分：again / good；新卡为 None
    last_rating: str | None = Field(default=None, max_length=16)
    # 上次独立首答对错（解释展示用；不参与判分口径）
    last_is_correct: bool | None = None
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── 队列 / 统计响应体（非表）─────────────────────────────────────────


class VocabularyReviewQueueItem(SQLModel):
    """队列条目：到期词条 + 可解释调度信息 + 词条当前内容。"""

    word_id: uuid.UUID
    headword: str
    part_of_speech: str | None = None
    meaning_zh: str
    meaning_en: str | None = None
    accepted_spellings: list[str] | None = None
    example_en: str | None = None
    audio_url: str | None = None
    morphology: list[dict[str, str]] | None = None
    capability: str
    state: str
    due_at: datetime
    overdue_days: int = 0
    last_review_at: datetime | None = None
    last_rating: str | None = None
    last_is_correct: bool | None = None
    interval_days: int | None = None
    reps: int = 0
    lapses: int = 0
    # 建议题型（与能力维度对齐；认读 → 选择题类，拼写 → 输入词形类）
    suggested_prompt_types: list[str] = []


class VocabularyReviewQueue(SQLModel):
    """GET /classes/{code}/vocabulary/student/review-queue。"""

    classroom_code: str
    generated_at: datetime
    # 每日负担摘要
    daily_limit: int
    reviewed_today_count: int
    due_today_count: int
    remaining_today_count: int
    items: list[VocabularyReviewQueueItem] = []


class VocabularyReviewStats(SQLModel):
    """个人成长页的真实复习统计（不宣称记忆留存率）。"""

    # 档案内词条 × 能力维度状态总数
    tracked_count: int = 0
    # 当前已到期（含逾期）条目数
    due_count: int = 0
    # 今日已复习条目数（按 last_review_at 落在今日自然日）
    reviewed_today_count: int = 0
    learning_count: int = 0
    review_count: int = 0
    recognition_count: int = 0
    spelling_count: int = 0
