"""版权/授权台账 + 词库版本历史（#517）API schema（非表模型）。

- 授权：来源类型 ``self_built/textbook/licensed/ai/demo``；textbook/licensed
  发布时必须带授权方 + 凭证（授权文号或授权书 URL），有效期填写则须未过期。
- 版本：词条集合快照 + 确定性哈希；支持列表、词条级对比、回滚（回滚生成新版本）。
"""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

# ── 版权/授权台账 ────────────────────────────────────────────────────

VOCAB_SOURCE_TYPES = ("self_built", "textbook", "licensed", "ai", "demo")
# 发布门禁要求授权齐备的来源类型；self_built/ai/demo 走既有审核 approved 门禁
LICENSE_REQUIRED_SOURCE_TYPES = ("textbook", "licensed")

# 发布门禁稳定错误码（detail 前缀，前端按码映射；措辞不随文案改动）
LICENSE_ERROR_OWNER_MISSING = "vocabulary_license_owner_missing"
LICENSE_ERROR_REF_MISSING = "vocabulary_license_ref_missing"
LICENSE_ERROR_EXPIRED = "vocabulary_license_expired"

# 授权状态：not_required=免授权；active=有效；expiring=临期（窗口内）；expired=已过期；
# missing=应授权来源缺授权方或凭证（平台台账只读口径，不参与发布门禁状态机）
LICENSE_STATUS_NOT_REQUIRED = "not_required"
LICENSE_STATUS_ACTIVE = "active"
LICENSE_STATUS_EXPIRING = "expiring"
LICENSE_STATUS_EXPIRED = "expired"
LICENSE_STATUS_MISSING = "missing"

# 临期提醒窗口（天）
LICENSE_EXPIRING_DAYS = 30

# 审计目标类型
LICENSE_TARGET_BOOK = "book"
LICENSE_TARGET_WORD = "word"


class VocabularyLicenseInfo(SQLModel):
    """授权信息（词库级或词条级通用视图）。"""

    source_type: str
    license_owner: str | None = None
    license_ref: str | None = None
    license_expires_at: datetime | None = None
    authorization_doc_url: str | None = None
    license_note: str | None = None
    license_status: str


class VocabularyLicenseUpdate(SQLModel):
    """授权信息更新请求；缺省字段不修改，可空字段传 null 清空。"""

    source_type: str | None = None
    license_owner: str | None = None
    license_ref: str | None = None
    license_expires_at: datetime | None = None
    authorization_doc_url: str | None = None
    license_note: str | None = None


class VocabularyWordLicenseItem(SQLModel):
    """词库授权详情中的词条级授权行。"""

    word_id: uuid.UUID
    headword: str
    source_type: str
    license_owner: str | None = None
    license_ref: str | None = None
    license_expires_at: datetime | None = None
    authorization_doc_url: str | None = None
    license_note: str | None = None
    license_status: str


class VocabularyBookLicenseDetail(SQLModel):
    """按词库读取授权：词库级信息 + 词条级授权清单。"""

    book_id: uuid.UUID
    title: str
    license: VocabularyLicenseInfo
    words: list[VocabularyWordLicenseItem] = []


class VocabularyLicenseAuditItem(SQLModel):
    """授权变更审计单行。"""

    id: uuid.UUID
    target_type: str
    book_id: uuid.UUID | None = None
    word_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    changes: dict[str, dict[str, str | None]] = {}
    note: str | None = None
    created_at: datetime | None = None
    tenant_slug: str | None = None
    tenant_name: str | None = None


class VocabularyLicenseAlertItem(SQLModel):
    """到期提醒单行：临期 / 已过期的词库或词条。"""

    target_type: str
    book_id: uuid.UUID
    book_title: str
    word_id: uuid.UUID | None = None
    headword: str | None = None
    source_type: str
    license_owner: str | None = None
    license_ref: str | None = None
    license_expires_at: datetime | None = None
    authorization_doc_url: str | None = None
    license_status: str


class VocabularyLicenseStatusItem(SQLModel):
    """平台授权台账单行：某校某词库的当前授权状态（只读，#517 运营台账页）。"""

    book_id: uuid.UUID
    title: str
    tenant_slug: str | None = None
    tenant_name: str | None = None
    source_type: str
    license_status: str
    license_owner: str | None = None
    license_ref: str | None = None
    authorization_doc_url: str | None = None
    license_expires_at: datetime | None = None
    license_note: str | None = None
    created_at: datetime | None = None


class VocabularyLicenseStatusList(SQLModel):
    """平台授权台账当前状态清单（只读）。"""

    items: list[VocabularyLicenseStatusItem] = []
    total: int = 0


# ── 词库版本历史 ────────────────────────────────────────────────────

# 版本动作类型
VERSION_ACTION_CREATE = "create"
VERSION_ACTION_ADD_WORDS = "add_words"
VERSION_ACTION_REMOVE_WORD = "remove_word"
VERSION_ACTION_EDIT_WORD = "edit_word"
VERSION_ACTION_REVIEW = "review"
VERSION_ACTION_ROLLBACK = "rollback"
VERSION_ACTIONS = (
    VERSION_ACTION_CREATE,
    VERSION_ACTION_ADD_WORDS,
    VERSION_ACTION_REMOVE_WORD,
    VERSION_ACTION_EDIT_WORD,
    VERSION_ACTION_REVIEW,
    VERSION_ACTION_ROLLBACK,
)

# 对比变更维度：meaning=释义；example=例句；morphology=词法；headword=词形
VERSION_FIELD_MEANING = "meaning"
VERSION_FIELD_EXAMPLE = "example"
VERSION_FIELD_MORPHOLOGY = "morphology"
VERSION_FIELD_HEADWORD = "headword"

DIFF_ADDED = "added"
DIFF_REMOVED = "removed"
DIFF_CHANGED = "changed"


class VocabularyBookVersionEntry(SQLModel):
    """版本列表单行（不含完整快照内容）。"""

    version_no: int
    action: str
    summary: str | None = None
    content_hash: str
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    word_count: int = 0
    created_at: datetime | None = None


class VocabularyBookVersionList(SQLModel):
    items: list[VocabularyBookVersionEntry] = []
    total: int = 0


class VocabularyVersionDiffEntry(SQLModel):
    """词条级对比单行：新增 / 删除 / 变更（含变更维度与前后条目）。"""

    word_id: uuid.UUID
    headword: str
    change_kind: str
    fields: list[str] = []
    from_entry: dict[str, object] | None = None
    to_entry: dict[str, object] | None = None


class VocabularyVersionCompare(SQLModel):
    book_id: uuid.UUID
    from_version_no: int
    to_version_no: int
    added: list[VocabularyVersionDiffEntry] = []
    removed: list[VocabularyVersionDiffEntry] = []
    changed: list[VocabularyVersionDiffEntry] = []
    total_changed: int = 0
