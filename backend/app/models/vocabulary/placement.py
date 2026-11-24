"""词汇粗分档自适应小测（placement）模型：结果历史表 + API schema。

边界（产品口径，2026-11-24 #517 批次）：

- 探针式粗分档，**不是精准定级、不是考试分数、不发认证**；结果只给「建议起点
  级别 + 推荐词库 + 说明」，不写学生等级字段（``Student.current_band`` 保持不动），
  不锁任务难度。
- 独立会话类型 ``kind="placement"``：不计入教师任务/自主练习统计，不写 FSRS
  复习状态，不推进农场 XP；作答落 ``VocabularyAnswer`` 仅作本测内判分留痕。
- 结果历史单独建表（``vocab_placement_result``），与学生等级字段物理隔离；
  可重测，历史全部保留，教师/管理员只读可见，仅作教学参考。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel

from app.models.base import _tenant_id_field, get_datetime_utc

# ── 分档口径（KET → PET → CET4 → ACADEMIC/IELTS_TOEFL 顶档合并）─────────
# 与五级常量 VOCAB_LEVEL_ORDER 的顺序无关：本测产品梯度固定为下序四档。
PLACEMENT_BAND_ORDER = ("KET", "PET", "CET4", "ADVANCED")
PLACEMENT_BAND_LEVELS: dict[str, tuple[str, ...]] = {
    "KET": ("KET",),
    "PET": ("PET",),
    "CET4": ("CET4",),
    "ADVANCED": ("ACADEMIC", "IELTS_TOEFL"),
}
# 顶档对外回填的代表五级级别（ADVANCED 合并 ACADEMIC/IELTS_TOEFL，展示用）
PLACEMENT_BAND_PRIMARY_LEVEL: dict[str, str] = {
    "KET": "KET",
    "PET": "PET",
    "CET4": "CET4",
    "ADVANCED": "ACADEMIC",
}
PLACEMENT_KIND = "placement"
PLACEMENT_DEFAULT_TOTAL = 12
PLACEMENT_MIN_CHOICE_WORDS = 4
PLACEMENT_START_BAND = "PET"
# 某档至少 2 次正确作答，建议起点才上移到该档
PLACEMENT_PASS_CORRECT = 2

# 说明/限制稳定标识（前端按标识映射中英双语；后端 detail 不改措辞）
LIMITATION_NONE = "none"
LIMITATION_MATERIAL_LIMITED = "material_limited"


class VocabPlacementResult(SQLModel, table=True):
    """一次完成的粗分档小测结果（历史留痕，可重测追加，不覆盖旧记录）。

    本表不是学生等级表：只记录本测的建议起点与素材限制，不回写 Student 等级
    字段，不参与任务成绩 / 自主练习统计 / FSRS 调度 / 农场 XP。
    """

    __tablename__ = "vocab_placement_result"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    session_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="vocabulary_session.id",
        ondelete="SET NULL",
        index=True,
    )
    # 建议起点档：KET / PET / CET4 / ADVANCED（粗分档，非定级）
    recommended_band: str = Field(max_length=16, index=True)
    # 回填的代表五级级别（ADVANCED → ACADEMIC）；无映射时为 None
    recommended_level: str | None = Field(default=None, max_length=16)
    recommended_book_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="vocabulary_book.id",
        ondelete="SET NULL",
    )
    recommended_book_title: str | None = Field(default=None, max_length=255)
    question_count: int = Field(ge=0)
    answered_count: int = Field(ge=0)
    correct_count: int = Field(ge=0)
    # none / material_limited：素材不足时按实际题量降级，明确告知限制
    limitation: str = Field(default=LIMITATION_NONE, max_length=32)
    submitted_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── API schema（非表）───────────────────────────────────────────────────


class PlacementChoice(SQLModel):
    """四选一选项（真实 approved 词条，不硬造释义）。"""

    word_id: uuid.UUID
    headword: str
    part_of_speech: str | None = None
    meaning_zh: str


class PlacementQuestion(SQLModel):
    item_index: int
    band: str
    headword: str
    part_of_speech: str | None = None
    choices: list[PlacementChoice]


class PlacementResultPublic(SQLModel):
    id: uuid.UUID
    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    recommended_band: str
    recommended_level: str | None = None
    recommended_book_id: uuid.UUID | None = None
    recommended_book_title: str | None = None
    question_count: int
    answered_count: int
    correct_count: int
    limitation: str = LIMITATION_NONE
    submitted_at: datetime | None = None


class PlacementStartResponse(SQLModel):
    session_id: uuid.UUID
    status: str
    planned_total: int
    answered_count: int
    degraded: bool
    limitation: str | None = None
    question: PlacementQuestion | None = None
    result: PlacementResultPublic | None = None


class PlacementAnswerRequest(SQLModel):
    item_index: int = Field(ge=0)
    answer: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)


class PlacementAnswerResponse(SQLModel):
    item_index: int
    is_correct: bool
    correct_headword: str
    meaning_zh: str
    answered_count: int
    planned_total: int
    status: str
    question: PlacementQuestion | None = None
    result: PlacementResultPublic | None = None


class PlacementHistoryResponse(SQLModel):
    items: list[PlacementResultPublic]
