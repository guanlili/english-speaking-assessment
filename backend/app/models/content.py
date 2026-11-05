"""题目内容模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import HTTPException
from pydantic import Field as PydanticField
from pydantic import field_validator
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    VOCAB_LEVEL_ORDER,
    _tenant_id_field,
    get_datetime_utc,
)

# ── 口语评测（第 2 周范围：课堂码 + 分级问答）────────────────────────
# PRD §8.4 功能树：内容（篇目/复述句/情景/词表档）、课堂（课堂码/显示名/练习会话）、
# 作答（录音/转写/分数/建议）。词表档是第 3 周内容，暂不建。


class ExamItemSettings(SQLModel):
    """Per-item exam timings; publishing freezes these settings in the snapshot."""

    wait_seconds: int = Field(default=3, ge=0, le=60)
    after_audio_seconds: int = Field(default=2, ge=0, le=60)
    prep_seconds: int | None = Field(default=None, ge=0, le=180)
    audio_url: str | None = Field(default=None, max_length=1024)


class PassageBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    # 主题单一事实源是所属单元：挂单元时由服务端派生为 unit.topic（见
    # crud.derive_passage_topic），此字段只在「未归属」篇目上由教师显式给定
    topic: str = Field(default="", max_length=100)
    cefr_band: str = Field(default="B1", max_length=10)
    text: str = Field(min_length=1)
    # 中文提示（可选）：学生端题干下方展示；空则回退题型固定提示
    translation: str | None = Field(default=None, max_length=1024)
    # 标准音地址；为空时前端用 speechSynthesis 兜底（PRD §7.2）
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=45, ge=10, le=180)
    is_active: bool = True


ReadingSentenceSeconds = Annotated[int, PydanticField(strict=True, ge=1, le=180)]


class Passage(PassageBase, table=True):
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()
    # C2：slug 校内唯一（两校可同名；单校窗口与旧全局唯一等价）
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_passage_tenant_slug"),
    )

    copied_from_id: uuid.UUID | None = Field(default=None)
    reading_sentence_seconds: list[ReadingSentenceSeconds | None] | None = Field(
        default=None, sa_type=JSON
    )
    # 拆句配音按句子原文寻址而非下标：改一句正文不影响其余句子的配音，
    # 正文编辑后失配的旧键不再命中（等同未配音，前端 speechSynthesis 兜底）。
    reading_sentence_audio: dict[str, str] | None = Field(default=None, sa_type=JSON)
    exam_settings: dict[str, object] | None = Field(default=None, sa_type=JSON)
    # 题库查重预计算（services/content_dedup.py 维护）：标题/正文的归一键
    # sha256；导入疑似重复判定走索引，不再全表流式拉原文
    dedup_title_hash: str | None = Field(default=None, max_length=64, index=True)
    dedup_text_hash: str | None = Field(default=None, max_length=64, index=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 唯一性由 (tenant_id, slug) 复合承接（C2）；索引保留供查找
    slug: str = Field(index=True, max_length=100)
    # 题库保留整篇文章；发布/学生题单按句展开为独立朗读题。
    reading_split: bool = False
    # 旧版拆分产生的独立篇目保留 ID/历史，归入原文章后不再单独选题。
    parent_passage_id: uuid.UUID | None = Field(
        default=None, foreign_key="passage.id", ondelete="CASCADE", index=True
    )
    # 所属学习单元（关卡）；为空时挂全局默认（老数据兼容）
    unit_id: uuid.UUID | None = Field(
        default=None, foreign_key="unit.id", ondelete="SET NULL", index=True
    )
    # 创建者：只有创建者和管理员能改/删；NULL = 存量无主内容，所有教师可改
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class PassagePublic(PassageBase):
    copied_from_id: uuid.UUID | None = None
    reading_sentence_seconds: list[ReadingSentenceSeconds | None] | None = None
    reading_sentence_audio: dict[str, str] | None = None
    id: uuid.UUID
    slug: str
    reading_split: bool = False
    # 所属单元：管理端要能读回指派关系（写入口同为 PassageCreate.unit_id）
    unit_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    created_at: datetime | None = None


class PassageCreate(PassageBase):
    # 留空则由服务端从标题自动生成（同名自动 -2/-3 去重）；显式给值仍查重 409
    slug: str | None = Field(default=None, max_length=100)
    unit_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _title_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped

    @field_validator("text")
    @classmethod
    def _text_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("正文不能为空")
        return stripped


# 学习单元（EIP 教材单元 → 学生端主题探索/学习路径）；顺序解锁 + 老师可全开
class Unit(SQLModel, table=True):
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_index: int = Field(default=0, ge=0, index=True)
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(max_length=100)
    is_active: bool = True
    # 题库查重预计算（services/content_dedup.py 维护）
    dedup_title_hash: str | None = Field(default=None, max_length=64, index=True)


class UnitPublic(SQLModel):
    id: uuid.UUID
    order_index: int
    title: str
    topic: str
    is_active: bool
    # 单元下的启用篇目数：管理端/老师端指派前的完整性检查（0 = 指派后学生无内容）
    passage_count: int = 0


class UnitCreate(SQLModel):
    order_index: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(max_length=100)
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def _title_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped


class UnitUpdate(SQLModel):
    order_index: int | None = None
    title: str | None = None
    topic: str | None = None
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def _title_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("标题不能为空")
        return stripped


# 听后复述句：属于篇目，由短到长排序（PRD §6：一轮 3 句）
# ── 分级题型训练（2026-10-03，PR A：题库与练习流程）────────────────
# 考试式题型 × 共享五级，两维分别建模（exam_kind 与 exam_level 两个独立
# 可空列）：旧数据两列为 NULL，含义与流程完全不变、不重新解释。
# 复用 RepeatSentence（听令复述类）与 ScenarioQuestion（问答类）两表。
EXAM_KIND_REPEAT = ("toefl_lnr",)  # TOEFL Listen and Repeat（复述表）

EXAM_KIND_QUESTION = (
    "interview",  # Take an Interview（问答题表）
    "ielts_p1",  # IELTS Part 1
    "ielts_p2",  # IELTS Part 2（话题卡 + 准备时间 + 长回答）
    "ielts_p3",  # IELTS Part 3
)

# 各级别均为课堂版本：KET/PET 级的题型靠内容本身降低语言难度与作答要求
# （更短 suggested_seconds、更简文本、prep_seconds 可更短），无需单独题型值


def validate_exam_fields(
    table: str,
    exam_kind: str | None,
    exam_level: str | None,
    cue_card_bullets: list[str] | None = None,
    prep_seconds: int | None = None,
) -> None:
    """考试字段校验：题型/级别合法、按表匹配、话题卡仅 Part 2。"""
    allowed = {
        "repeat": EXAM_KIND_REPEAT,
        "question": EXAM_KIND_QUESTION,
    }
    if exam_kind is None:
        if exam_level is not None or cue_card_bullets or prep_seconds is not None:
            raise HTTPException(
                status_code=422,
                detail="未选择考试题型时不能单独设置级别/话题卡/准备时间",
            )
        return
    if exam_kind not in allowed.get(table, ()):
        raise HTTPException(status_code=422, detail="未知考试题型")
    if exam_level is None:
        # 明确禁止「有题型、无级别」的记录：分级题型训练的题必须标注级别，
        # 否则教师端编辑会把它误降级为普通题
        raise HTTPException(status_code=422, detail="选择考试题型时需同时标注级别")
    if exam_level not in VOCAB_LEVEL_ORDER:
        raise HTTPException(
            status_code=422,
            detail="考试级别无效，可选：" + "/".join(VOCAB_LEVEL_ORDER),
        )
    if cue_card_bullets is not None and exam_kind != "ielts_p2":
        raise HTTPException(
            status_code=422, detail="话题卡要点仅支持 IELTS Part 2 题型"
        )
    if prep_seconds is not None and not (10 <= prep_seconds <= 180):
        raise HTTPException(status_code=422, detail="准备时间须在 10–180 秒之间")


def validate_question_suggested_seconds(
    suggested_seconds: int, exam_kind: str | None
) -> None:
    """作答时长口径：普通情景问法 ≤60 秒；考试题（长回答）≤300 秒。"""
    limit = 300 if exam_kind else 60
    if not (10 <= suggested_seconds <= limit):
        raise HTTPException(
            status_code=422,
            detail=f"建议秒数需在 10–{limit} 之间（考试题型支持长回答）",
        )


# ── 句型推荐与收藏（PR B）──────────────────────────────────────────
# 可替换句型：按共享五级 + 表达用途分类，供学生答题时套用/替换。
# exam_kind 可空=通用句型（任何考试式题型均推荐）；收藏挂学生课堂档案
# （跨设备：同账号任何设备登录后可见同一份收藏）。
FRAME_PURPOSES = (
    "opinion",  # 表达观点
    "reason",  # 给出理由
    "example",  # 举例说明
    "compare",  # 比较对比
    "describe",  # 描述人/物/事
    "past",  # 回忆经历
    "future",  # 展望计划
)


class SentenceFrame(SQLModel, table=True):
    __tablename__ = "sentence_frame"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 共享五级（必填）：推荐时按题目实际难度匹配
    level: str = Field(max_length=16, index=True)
    # 表达用途（FRAME_PURPOSES 之一）
    purpose: str = Field(max_length=24, index=True)
    # 关联考试题型（可空=通用，任何考试式题型均推荐）
    exam_kind: str | None = Field(default=None, max_length=24)
    text_en: str = Field(min_length=1, max_length=255)
    text_zh: str = Field(min_length=1, max_length=255)
    status: str = Field(default="active", max_length=16, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class StudentExpressionFavorite(SQLModel, table=True):
    """评分里收藏的升级表达。挂课堂档案，换设备仍在。"""

    __tablename__ = "student_expression_favorite"
    __table_args__ = (
        UniqueConstraint("student_id", "text", name="uq_student_expression_text"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(
        foreign_key="student.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    text: str = Field(min_length=1, max_length=500)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ExpressionFavoritePublic(SQLModel):
    id: uuid.UUID
    text: str


class ExpressionFavoriteCreate(SQLModel):
    texts: list[str] = Field(min_length=1, max_length=20)


class StudentFrameFavorite(SQLModel, table=True):
    __tablename__ = "student_frame_favorite"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 挂学生课堂档案：跨设备（同账号任何设备登录可见同一份收藏）
    student_id: uuid.UUID = Field(
        foreign_key="student.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    frame_id: uuid.UUID = Field(
        foreign_key="sentence_frame.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    __table_args__ = (
        UniqueConstraint("student_id", "frame_id", name="uq_student_frame_favorite"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()


class SentenceFramePublic(SQLModel):
    id: uuid.UUID
    level: str
    purpose: str
    exam_kind: str | None = None
    text_en: str
    text_zh: str
    status: str = "active"
    # 学生视角：是否已收藏（管理端恒 false）
    favorited: bool = False


class RepeatSentence(SQLModel, table=True):
    copied_from_id: uuid.UUID | None = Field(default=None)
    __tablename__ = "repeat_sentence"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    exam_settings: dict[str, object] | None = Field(default=None, sa_type=JSON)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 可空：2026-09-29 起复述句可独立存在（题目库直接创建、指派直接选用）；
    # 挂到篇目时仍随篇目出现在自主练习轮里
    passage_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="passage.id",
        nullable=True,
        ondelete="CASCADE",
        index=True,
    )
    order_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    translation: str | None = Field(default=None, max_length=1024)
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=8, ge=3, le=60)
    # 听句复述可重听次数：0=不限，默认 3；服务端按学生×会话×题目计数防刷
    replay_limit: int = Field(
        default=3, ge=0, le=9, sa_column_kwargs={"server_default": "3"}
    )
    # 题库查重预计算（services/content_dedup.py 维护）
    dedup_text_hash: str | None = Field(default=None, max_length=64, index=True)
    # 分级题型训练（可空=普通课堂内容，含义不变）：题型与级别分别建模
    exam_kind: str | None = Field(default=None, max_length=24)
    exam_level: str | None = Field(default=None, max_length=16)
    # 创建者：挂篇目的句子按篇目创建者判定权限，独立句按本列
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# 情景主题（来自 EIP），同主题一组问法分属低/中/高档（PRD §8.4）
class Scenario(SQLModel, table=True):
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()
    # C2：topic 校内唯一（两校可同名主题；单校窗口与旧全局唯一等价）
    __table_args__ = (
        UniqueConstraint("tenant_id", "topic", name="uq_scenario_tenant_topic"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 唯一性由 (tenant_id, topic) 复合承接（C2）；索引保留供查找
    topic: str = Field(index=True, max_length=100)
    is_active: bool = True
    # 创建者：改名/启停归创建者；NULL = 存量或管理员建的公共主题
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    # 题库查重预计算（services/content_dedup.py 维护）
    dedup_topic_hash: str | None = Field(default=None, max_length=64, index=True)


class ScenarioQuestion(SQLModel, table=True):
    copied_from_id: uuid.UUID | None = Field(default=None)
    __tablename__ = "scenario_question"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    exam_settings: dict[str, object] | None = Field(default=None, sa_type=JSON)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scenario_id: uuid.UUID = Field(
        foreign_key="scenario.id", nullable=False, ondelete="CASCADE", index=True
    )
    # 历史字段：问答已不分级（2026-09-29 产品决策，老师自由编排题目），
    # 抽题与展示均不再使用；保留列兼容存量数据，缺省落 B1
    band: str = Field(default="B1", max_length=10, index=True)
    order_index: int = Field(default=0, ge=0)
    text: str = Field(min_length=1)
    translation: str | None = Field(default=None, max_length=1024)
    audio_url: str | None = Field(default=None, max_length=1024)
    # 长回答（IELTS Part 2）上限 300 秒；普通问法仍 ≤60（由校验函数按题型把关）
    suggested_seconds: int = Field(default=20, ge=10, le=300)
    # 分级题型训练（可空=普通情景问法）：interview / ielts_p1/p2/p3 × 五级
    exam_kind: str | None = Field(default=None, max_length=24)
    exam_level: str | None = Field(default=None, max_length=16)
    # IELTS Part 2 话题卡要点（仅 ielts_p2；提示学生可展开的要点）
    cue_card_bullets: list[str] | None = Field(
        default=None, sa_column=Column("cue_card_bullets", JSON, nullable=True)
    )
    # 准备时间（秒）：Part 2 话题卡准备（默认建议 60，可按级别缩短）
    prep_seconds: int | None = Field(default=None, ge=10, le=180)
    # 创建者按题记录：主题是共用分组，任何教师都能往别人的主题里加题
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    # 题库查重预计算（services/content_dedup.py 维护）
    dedup_text_hash: str | None = Field(default=None, max_length=64, index=True)


class ScenarioQuestionPublic(SQLModel):
    copied_from_id: uuid.UUID | None = None
    id: uuid.UUID
    band: str
    text: str
    audio_url: str | None = None
    suggested_seconds: int
    owner_id: uuid.UUID | None = None
    # 分级题型训练（可空=普通情景问法）
    exam_kind: str | None = None
    exam_level: str | None = None
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None


# 题目说明（第四种题型）：纯文字引导页，组卷时插入题与题之间。
# 学生阅读后点「继续」进入下一题，无录音作答——模考里占一个计时窗口
# （时长=suggested_seconds，可提前点继续，到时自动翻页），普通练习不强制停留。
class Instruction(SQLModel, table=True):
    copied_from_id: uuid.UUID | None = Field(default=None)
    __tablename__ = "instruction"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    exam_settings: dict[str, object] | None = Field(default=None, sa_type=JSON)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 可选小标题：说明卡与组卷列表里作题头区分用途（如「Part B 开始」）
    title: str | None = Field(default=None, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    # 建议停留秒数：模考窗口时长（普通练习仅作提示，不强制）
    suggested_seconds: int = Field(default=20, ge=5, le=300)
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    # 题库查重预计算（services/content_dedup.py 维护）
    dedup_text_hash: str | None = Field(default=None, max_length=64, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class InstructionPublic(SQLModel):
    copied_from_id: uuid.UUID | None = None
    id: uuid.UUID
    title: str | None = None
    text: str
    suggested_seconds: int
    owner_id: uuid.UUID | None = None


# 学生点「继续」的确认记录：说明无作答，用 ack 表达「已读」——
# 普通练习里驱动题单流转，模考里驱动题窗推进，教师面板显示已读状态
class InstructionAck(SQLModel, table=True):
    __tablename__ = "instruction_ack"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "session_id", "item_id", name="uq_instruction_ack_scope"
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="student.id", ondelete="CASCADE")
    session_id: uuid.UUID = Field(foreign_key="practice_session.id", ondelete="CASCADE")
    # 指向 instruction.id（快照已深拷贝文字，题库删除不影响历史练习）
    item_id: uuid.UUID = Field(index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── 题库批量导入导出（2026-10-14：老师自助录题）──────────────────────
# 模板下载 → Excel/CSV 上传 → 预览（不落库）→ 确认导入（单事务）。
# 只写现有四张题型表、只 INSERT 不 UPDATE；详细口径见 services/question_bank_io.py。
QUESTION_BANK_TYPES = ("passage", "repeat", "question", "instruction")


class QuestionBankTypeCount(SQLModel):
    """预览：单个题型工作表的分类计数。"""

    type: str  # QUESTION_BANK_TYPES 之一
    valid_count: int  # 将新建（默认不含疑似重复）
    exact_duplicate_count: int  # 完全重复，导入时自动跳过
    suspected_duplicate_count: int  # 疑似重复，需老师确认是否导入
    invalid_count: int  # 校验/歧义错误行（可下载待修正数据）
    missing_audio_count: int  # 将新建且缺音频的题数（信息性提示，不阻断）


class QuestionBankImportIssue(SQLModel):
    """行级问题定位：题型（即工作表）+ 行号 + 中文稳定标识原因（前端双语映射）。"""

    type: str
    line: int
    reason: str


class QuestionBankSuspectedItem(SQLModel):
    """疑似重复逐条确认单元：待导入行 vs 已有候选（库内或同批前序行）的
    关键字段快照。键是 canonical 字段名（稳定标识），前端映射双语标签；
    行标识 (type, line) 绑定当前文件，确认时按此对账。"""

    type: str
    line: int
    reason: str
    incoming: dict[str, str]
    existing: dict[str, str]


class QuestionBankCreatedItem(SQLModel):
    """确认导入新建条目引用：支撑「查看本批 / 带入组卷 / 补齐音频」。
    无批次表——批次即本次响应，前端按 id 使用现有能力。"""

    type: str
    id: str
    label: str  # 标题或题干节选（展示用）
    topic: str | None = None  # 仅问答题：所属主题（组卷 scenario 反查备用）
    needs_audio: bool  # 仅听句复述：题面不显示文字 + 模考开考检查，缺音频影响作答
    audio_missing: bool


class QuestionBankImportPreview(SQLModel):
    sheets: list[QuestionBankTypeCount]  # 只列文件中出现的题型
    issues: list[QuestionBankImportIssue]
    issues_truncated: bool
    suspected: list[QuestionBankSuspectedItem]  # 疑似重复逐条明细+两侧对照
    suspected_truncated: bool
    invalid_total: int  # 全部错误行（含解析期题型无效行；错误下载的依据）
    fingerprint: str  # 预览指纹：确认时锁内比对，内容变化即要求重新预览
    new_topics: list[str]  # 将自动新建的问答主题
    unit_fallback_count: int  # 单元未匹配、按无单元导入的篇目数
    standalone_sentence_count: int  # 挂靠篇目未匹配、按独立句导入的句数
    total_valid: int


class QuestionBankImportTypeResult(SQLModel):
    """确认导入：单个题型的落库结果。"""

    type: str
    created: int
    skipped_duplicate: int
    skipped_suspected: int  # 未被逐条勾选「导入」的疑似行数
    skipped_invalid: int
    missing_audio_count: int


class QuestionBankImportResult(SQLModel):
    sheets: list[QuestionBankImportTypeResult]
    created_topics: list[str]
    created_items: list[QuestionBankCreatedItem]  # 本批新建条目（按真实 ID）
    issues: list[QuestionBankImportIssue]
    missing_audio_total: int
