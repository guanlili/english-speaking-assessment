"""词汇模型：五级词库 schema 与分级工具（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    VOCAB_LEVEL_ORDER,
    _tenant_id_field,
    get_datetime_utc,
)
from app.models.vocabulary.words import (
    VocabularyWordIn,
)


def effective_vocab_level(levels: list[str]) -> str | None:
    """按固定顺序取最早（最易）一级。"""
    levels_valid = [level for level in levels if level in VOCAB_LEVEL_ORDER]
    if not levels_valid:
        return None
    return min(levels_valid, key=VOCAB_LEVEL_ORDER.index)


class VocabularyLevelEntry(SQLModel, table=True):
    """五级分级词条。

    - 同词可出现在多个级别（每级一行），实际难度按固定顺序取最易一级；
    - 同形异义：同 (headword, level) 不同释义各占一行（sense_no 区分），
      同义词不是同形异义，也绝不进入任何词条的「可接受拼写」；
    - sources 保留来源标签（如 KET 跨天、学术双文件、雅思场景）；
    - PET 等扫描件 OCR 行 needs_review=true，人工核对后才可启用。
    """

    __tablename__ = "vocab_level_entry"
    __table_args__ = (
        UniqueConstraint("headword", "level", "sense_no", name="uq_vocab_level_sense"),
        Index("ix_vocab_level_level_headword", "level", "headword"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 匹配键：NFKC + 去首尾空白 + casefold（与拼写判分同口径）
    headword: str = Field(max_length=64, index=True)
    level: str = Field(max_length=16)
    # 同形异义序号：同 (headword, level) 下从 1 递增
    sense_no: int = Field(default=1, ge=1)
    part_of_speech: str | None = Field(default=None, max_length=32)
    meaning_zh: str | None = Field(default=None, max_length=255)
    # 词组（headword 含空格，如 put off）：入库保留，口语逐词命中统计暂不计入
    is_phrase: bool = Field(default=False, sa_column_kwargs={"server_default": "false"})
    # OCR/来源存疑行：人工核对后才可启用
    needs_review: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    note: str | None = Field(default=None, max_length=512)
    # 来源标签列表（同词同级多来源合并保留）
    sources: list[str] = Field(default_factory=list, sa_column=Column("sources", JSON))
    status: str = Field(default="active", max_length=16)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── 五级词库 API schema（请求/响应体，非表）────────────────────────

VOCAB_LEVEL_IMPORT_MAX_ROWS = 20000


class VocabularyLevelEntryPublic(SQLModel):
    id: uuid.UUID
    headword: str
    level: str
    sense_no: int
    part_of_speech: str | None = None
    meaning_zh: str | None = None
    is_phrase: bool = False
    needs_review: bool = False
    note: str | None = None
    sources: list[str] = []
    status: str = "active"


class VocabularyLevelEntryUpdate(SQLModel):
    """人工核对修正：缺省不修改；needs_review=False 即「已核对」。"""

    part_of_speech: str | None = None
    meaning_zh: str | None = None
    note: str | None = None
    needs_review: bool | None = None
    status: str | None = None


class VocabularyLevelLevelCount(SQLModel):
    level: str
    entry_count: int = 0
    phrase_count: int = 0
    needs_review_count: int = 0


class VocabularyLevelStats(SQLModel):
    levels: list[VocabularyLevelLevelCount] = []
    total_entries: int = 0
    total_sources: int = 0


class VocabularyLevelImportIssue(SQLModel):
    """导入预览的问题行。kind: invalid | duplicate_in_file | cross_level_conflict"""

    kind: str
    line: int
    headword: str
    reason: str
    # 跨级冲突时附：已存在的更易级别
    existing_level: str | None = None


class VocabularyLevelImportPreview(SQLModel):
    level: str
    source_label: str
    valid_rows: list[VocabularyWordIn]
    invalid: list[VocabularyLevelImportIssue]
    duplicates_in_file: list[VocabularyLevelImportIssue]
    cross_level_conflicts: list[VocabularyLevelImportIssue]
    # 确认导入后将新增/合并的行数与导入后各级数量
    new_count: int
    merge_count: int
    counts_after: list[VocabularyLevelLevelCount]


class VocabularyLevelImportResult(SQLModel):
    imported_new: int
    merged_existing: int
    skipped_invalid: int
    counts: list[VocabularyLevelLevelCount]


class VocabularyLevelWordInfo(SQLModel):
    """词条的五级归属信息（挂到背单词词条/口语命中上）。"""

    level: str | None = None
    all_levels: list[str] = []
