"""词汇模型：AI 备课与学情辅助（含缓存表）（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    _tenant_id_field,
    get_datetime_utc,
)

# ── 词汇 AI 备课与学情辅助（2026-10-06）────────────────────────────
# 红线：拼写对错仍由确定性规则判分；模型输出按不可信内容处理；
# 学生身份信息（姓名/学号/邮箱）不进入模型提示词。

VOCAB_AI_DRAFT_MAX = 20

VOCAB_AI_THEME_MAX = 120

VOCAB_AI_HINT_MAX = 300

# 每用户限流（次/窗口秒）；默认 10 次/小时
VOCAB_AI_RATE_LIMIT = 10

VOCAB_AI_RATE_WINDOW_S = 3600


class VocabularyAiCache(SQLModel, table=True):
    """AI 结果缓存：按 scope 的内容指纹判定新旧，记录变化后标记待更新。

    cache_key 唯一（kind + scope 维度 + 参数哈希）；fingerprint 是底层
    真实数据（作答计数/最大作答 id 等）的指纹——数据变化即指纹变化，
    下次生成会刷新缓存，命中旧指纹时把 stale 标记回给前端显示待更新。
    """

    __tablename__ = "vocabulary_ai_cache"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    cache_key: str = Field(max_length=128, unique=True)
    kind: str = Field(max_length=32, index=True)
    # 所属学生（讲解/学情）；教师词稿生成不落缓存
    student_id: uuid.UUID | None = Field(
        default=None, foreign_key="student.id", ondelete="CASCADE", index=True
    )
    payload: dict[str, object] = Field(
        sa_column=Column("payload", JSON, nullable=False)
    )
    fingerprint: str = Field(default="", max_length=255)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabularyAiWordDraft(SQLModel):
    """AI 词条草稿（教师预览/编辑后确认入库；不自动发布任务）。

    不包含 accepted_spellings——可接受拼写变体只能由教师显式维护，
    不让 AI 自行生成。
    """

    headword: str
    part_of_speech: str | None = None
    meaning_zh: str
    meaning_en: str | None = None
    example_en: str | None = None


class VocabularyAiWordDraftsRequest(SQLModel):
    theme: str = Field(min_length=1, max_length=VOCAB_AI_THEME_MAX)
    # 五级词库级别（KET/PET/ACADEMIC/CET4/IELTS_TOEFL），可选
    level: str | None = None
    count: int = Field(default=10, ge=1, le=VOCAB_AI_DRAFT_MAX)
    # 补充要求（可选，长度受限）
    hint: str | None = Field(default=None, max_length=VOCAB_AI_HINT_MAX)


class VocabularyAiWordDraftsResponse(SQLModel):
    drafts: list[VocabularyAiWordDraft] = []
    requested_count: int
    generated_at: datetime
    # 模型返回里被格式/去重检查丢弃的条数（透明展示）
    dropped_count: int = 0


class VocabularyAiWordDraftImportRequest(SQLModel):
    book_id: uuid.UUID
    # 教师可编辑后的草稿；服务端剥离 accepted_spellings 等不可信字段
    drafts: list[VocabularyAiWordDraft] = Field(min_length=1)


class VocabularyAiWordDraftImportResult(SQLModel):
    added: int
    skipped: int  # 与词库现有词条重复而被跳过
    book_word_count: int


class VocabularyAiWordExplanation(SQLModel):
    """单词结构化讲解：词义/常见误拼/记忆提示/例句（非聊天，单轮）。"""

    headword: str
    meaning_zh: str
    meanings: list[str] = []
    common_misspellings: list[str] = []
    memory_tips: list[str] = []
    examples: list[str] = []
    generated_at: datetime
    cached: bool = False
    # 底层记录变化后旧缓存未刷新时为 True（前端显示待更新）
    stale: bool = False


class VocabularyAiExplanationRequest(SQLModel):
    headword: str = Field(min_length=1, max_length=64)
    meaning_zh: str = Field(min_length=1, max_length=255)
    part_of_speech: str | None = Field(default=None, max_length=32)
    force: bool = False


class VocabularyAiWeakWord(SQLModel):
    """薄弱词：必须对应真实作答证据（学生首答输入 + 正确拼写）。"""

    headword: str
    meaning_zh: str
    your_answer: str
    correct_spelling: str


class VocabularyAiSessionInsightRequest(SQLModel):
    session_id: uuid.UUID
    force: bool = False


class VocabularyAiInsightScope(SQLModel):
    answered_count: int = 0
    total_count: int = 0
    # 整体学情：窗口参数与覆盖的作答时间范围
    rounds: int | None = None
    days: int | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None


class VocabularyAiSessionInsight(SQLModel):
    """单次练习学情：只用本轮真实作答；薄弱词逐条对应证据。"""

    summary: str
    weak_words: list[VocabularyAiWeakWord] = []
    suggestions: list[str] = []
    scope: VocabularyAiInsightScope
    generated_at: datetime
    cached: bool = False
    stale: bool = False


class VocabularyAiOverallInsightRequest(SQLModel):
    # 明确数量与时间范围：最近 limit 轮、最近 days 天（双上限防滥用）
    limit: int = Field(default=10, ge=1, le=30)
    days: int = Field(default=30, ge=1, le=180)
    force: bool = False


class VocabularyAiOverallInsight(SQLModel):
    """整体学习建议：基于明确范围内的历史记录；不给学生贴标签。"""

    summary: str
    weak_words: list[VocabularyAiWeakWord] = []
    suggestions: list[str] = []
    scope: VocabularyAiInsightScope
    generated_at: datetime
    cached: bool = False
    stale: bool = False
