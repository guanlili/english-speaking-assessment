"""词汇模型：词库/词条/CSV 导入的请求响应体（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from pydantic import field_validator
from sqlmodel import Field, SQLModel

# ── 考试标签与 CEFR 档位（#517 扩展区）──────────────────────────────
# exam_tags 为多选内容标签；取值限定下列考试体系。CEFR 只是词条内容
# 标签（A1–C2），不构成对学生的等级评定或测评结论。
VOCAB_EXAM_TAGS = ("SAT", "ACT", "GRE", "CET4", "IELTS", "TOEFL")
# 扩展区（高级备考词）判定标签：命中其一即进入高级分区。
ADVANCED_EXAM_TAGS = ("SAT", "ACT", "GRE")
VOCAB_CEFR_BANDS = ("A1", "A2", "B1", "B2", "C1", "C2")


def normalize_exam_tags(raw: list[str] | None) -> list[str]:
    """规范化考试标签：去空白、大写、去重；非法取值抛 ValueError。"""
    if raw is None:
        return []
    cleaned: list[str] = []
    for item in raw:
        tag = str(item).strip().upper()
        if not tag:
            continue
        if tag not in VOCAB_EXAM_TAGS:
            raise ValueError(f"exam_tag_invalid:{tag}")
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def normalize_cefr_band(raw: str | None) -> str | None:
    """规范化 CEFR 档位：空串 → None；非法取值抛 ValueError。"""
    if raw is None:
        return None
    band = str(raw).strip().upper()
    if not band:
        return None
    if band not in VOCAB_CEFR_BANDS:
        raise ValueError("cefr_band_invalid")
    return band


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

# ── 内容治理（AC4）：来源 / 审核状态 / 留痕备注标识 ──────────────────
# source: teacher=教师手动录入；ai=AI 草稿入库；textbook=五级词库目录转入；
# demo=演示种子；import=CSV/存量导入
VOCAB_WORD_SOURCES = ("teacher", "ai", "textbook", "demo", "import")
# review_status: draft 预留不产生行；当前写路径只产生 pending/approved
VOCAB_REVIEW_STATUSES = ("draft", "pending", "approved", "rejected")
# 审核备注的稳定标识（detail/note 不随文案改措辞）
REVIEW_NOTE_LEGACY = "legacy"
REVIEW_NOTE_SELF_CONFIRMED = "self_confirmed"
REVIEW_NOTE_LEVEL_CATALOG_VERIFIED = "level_catalog_verified"
REVIEW_NOTE_EDITED_AFTER_APPROVAL = "edited_after_approval"


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
    # 考试标签（多选）与 CEFR 档位：仅内容标签，不代表对学生的测评结论
    exam_tags: list[str] | None = None
    cefr_band: str | None = None

    @field_validator("exam_tags")
    @classmethod
    def _check_exam_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_exam_tags(value)

    @field_validator("cefr_band")
    @classmethod
    def _check_cefr_band(cls, value: str | None) -> str | None:
        return normalize_cefr_band(value)


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
    exam_tags: list[str] | None = None
    cefr_band: str | None = None
    # 词条级乐观锁：UI 传当前 version；不一致 409
    expected_version: int | None = Field(default=None, ge=1)

    @field_validator("exam_tags")
    @classmethod
    def _check_exam_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_exam_tags(value)

    @field_validator("cefr_band")
    @classmethod
    def _check_cefr_band(cls, value: str | None) -> str | None:
        return normalize_cefr_band(value)


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
    # 内容治理（AC4）
    source: str = "teacher"
    review_status: str = "pending"
    reviewer_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    version: int = 1
    # 五级归属（两模块共用分级数据源）：实际难度=最早一级；未命中分级时为 null
    level: str | None = None
    all_levels: list[str] = []
    # 考试标签（多选）与 CEFR 档位：仅内容标签；学生侧只展示 CEFR，不做等级评定
    exam_tags: list[str] = []
    cefr_band: str | None = None


class VocabularyBookCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    scope: str = Field(default="classroom", max_length=16)
    # scope=classroom 时必填；scope=public 仅管理员
    classroom_id: uuid.UUID | None = None
    # 内容治理（AC4）：本库词条来源；confirm_reviewed= 教师已核对 → 直接 approved
    source: str = Field(default="teacher", max_length=16)
    confirm_reviewed: bool = False
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


# ── 内容治理审核队列（AC4）───────────────────────────────────────────


class VocabularyReviewItem(SQLModel):
    """审核队列单行：词条当前内容 + 归属词库与审核留痕。"""

    word_id: uuid.UUID
    headword: str
    part_of_speech: str | None = None
    meaning_zh: str
    source: str
    review_status: str
    review_note: str | None = None
    version: int
    book_id: uuid.UUID | None = None
    book_title: str | None = None
    reviewer_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    # 平台运营跨校视图附加字段；校级端点不返回
    tenant_slug: str | None = None
    tenant_name: str | None = None


class VocabularyContentReviewList(SQLModel):
    items: list[VocabularyReviewItem] = []
    total: int = 0
    pending_count: int = 0
    rejected_count: int = 0
    approved_count: int = 0


class VocabularyReviewActionRequest(SQLModel):
    word_ids: list[uuid.UUID] = Field(min_length=1)
    action: str  # approve | reject
    note: str | None = None


class VocabularyReviewActionResult(SQLModel):
    updated: int
    status: str  # approved | rejected


class VocabularyReviewAuditItem(SQLModel):
    id: uuid.UUID
    word_id: uuid.UUID
    headword: str
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action: str
    from_status: str | None = None
    to_status: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    tenant_slug: str | None = None
    tenant_name: str | None = None
