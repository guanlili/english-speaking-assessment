"""词汇模型：词库/词条/CSV 导入的请求响应体（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

# ── 词汇模块 API schema（请求/响应体，非表）────────────────────────

# 出题方式：
#   meaning = 看义拼词（中文释义 → 输入英文）
#   audio   = 听音拼词（标准音 → 输入英文）
#   en_zh   = 英译中快测（英文 → 选中文释义，选项冻结在快照里）
#   zh_en   = 中译英快测（中文 → 选英文单词，选项冻结在快照里）
#   cloze   = 语境填空（例句挖空 → 输入目标词）
#   roots   = 词根词缀拼装（给定语素块 → 拼出单词）
# 前两种是拼写题，后四种是识别/组装题；判分统一在服务端、按首答计成绩。
VOCAB_PROMPT_TYPES = ("meaning", "audio", "en_zh", "zh_en", "cloze", "roots")
# 需要例句/词法素材的出题方式：内容不合格的词条不会进入这两种题
CONTENT_PROMPT_TYPES = ("cloze", "roots")
# 选择题型：选项由发布时的词单生成并固化，保证同一任务选项不漂移
CHOICE_PROMPT_TYPES = ("en_zh", "zh_en")


class VocabularyWordIn(SQLModel):
    """创建/导入词条的请求体（词库内新增词）。"""

    headword: str = Field(min_length=1, max_length=64)
    part_of_speech: str | None = Field(default=None, max_length=32)
    meaning_zh: str = Field(min_length=1, max_length=255)
    meaning_en: str | None = Field(default=None, max_length=255)
    accepted_spellings: list[str] | None = None
    example_en: str | None = Field(default=None, max_length=512)
    audio_url: str | None = Field(default=None, max_length=1024)
    # 词根词缀拆解：[{text, gloss, kind}]，kind ∈ prefix/root/suffix；
    # 拼接结果必须等于 headword 才可用于「词根拼装」题（发布时校验）
    morphology: list[dict[str, str]] | None = None


class VocabularyWordUpdate(SQLModel):
    """编辑词条：缺省不修改；可空字段传 null 清空。"""

    part_of_speech: str | None = None
    meaning_zh: str | None = Field(default=None, min_length=1, max_length=255)
    meaning_en: str | None = None
    accepted_spellings: list[str] | None = None
    example_en: str | None = None
    audio_url: str | None = None
    morphology: list[dict[str, str]] | None = None
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
    morphology: list[dict[str, str]] | None = None
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
