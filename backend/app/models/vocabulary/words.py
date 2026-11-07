"""词汇模型：词库/词条/CSV 导入的请求响应体（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

# ── 词汇模块 API schema（请求/响应体，非表）────────────────────────

VOCAB_PROMPT_TYPES = ("meaning", "audio")


class VocabularyWordIn(SQLModel):
    """创建/导入词条的请求体（词库内新增词）。"""

    headword: str = Field(min_length=1, max_length=64)
    part_of_speech: str | None = Field(default=None, max_length=32)
    meaning_zh: str = Field(min_length=1, max_length=255)
    meaning_en: str | None = Field(default=None, max_length=255)
    accepted_spellings: list[str] | None = None
    example_en: str | None = Field(default=None, max_length=512)
    audio_url: str | None = Field(default=None, max_length=1024)


class VocabularyWordUpdate(SQLModel):
    """编辑词条：缺省不修改；可空字段传 null 清空。"""

    part_of_speech: str | None = None
    meaning_zh: str | None = Field(default=None, min_length=1, max_length=255)
    meaning_en: str | None = None
    accepted_spellings: list[str] | None = None
    example_en: str | None = None
    audio_url: str | None = None
    status: str | None = None


class VocabularyWordPublic(SQLModel):
    id: uuid.UUID
    headword: str
    part_of_speech: str | None = None
    meaning_zh: str
    meaning_en: str | None = None
    accepted_spellings: list[str] | None = None
    example_en: str | None = None
    audio_url: str | None = None
    status: str = "active"
    # 五级归属（两模块共用分级数据源）：实际难度=最早一级；未命中分级时为 null
    level: str | None = None
    all_levels: list[str] = []


class VocabularyBookCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    scope: str = Field(default="classroom", max_length=16)
    # scope=classroom 时必填；scope=public 仅管理员
    classroom_id: uuid.UUID | None = None
    # 创建时一并入库的词条（来自导入预览或手动录入）
    words: list[VocabularyWordIn] = []


class VocabularyBookUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None


class VocabularyBookPublic(SQLModel):
    id: uuid.UUID
    title: str
    description: str | None = None
    scope: str
    classroom_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    status: str
    word_count: int = 0
    created_at: datetime | None = None


class VocabularyBookDetail(VocabularyBookPublic):
    words: list[VocabularyWordPublic] = []


class VocabularyImportRow(SQLModel):
    """导入预览里解析成功的一行（已规范化）。"""

    line: int
    word: VocabularyWordIn


class VocabularyImportIssue(SQLModel):
    line: int
    reason: str


class VocabularyImportPreview(SQLModel):
    rows: list[VocabularyImportRow]
    invalid: list[VocabularyImportIssue]
    duplicates: list[VocabularyImportIssue]
