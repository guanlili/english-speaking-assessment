"""词库模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    VOCAB_LEVEL_ORDER,
    _tenant_id_field,
    get_datetime_utc,
)

# ── 词汇学习（背单词模块，2026-10-01 设计文档 P0）──────────────────
# 与口语问答词汇分析用的五级词库完全分离：这里存的是可考的
# 教学词条（词性/释义/可接受拼写），历史作答永远按发布快照判分与展示。


class VocabularyWord(SQLModel, table=True):
    """一条可考的词义；同形异义各有独立行（不共用 lemma 唯一约束）。"""

    __tablename__ = "vocabulary_word"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 词形展示与判分主拼写；判分另接受 accepted_spellings 里的显式变体
    headword: str = Field(max_length=64, index=True)
    part_of_speech: str | None = Field(default=None, max_length=32)
    meaning_zh: str = Field(min_length=1, max_length=255)
    meaning_en: str | None = Field(default=None, max_length=255)
    # 额外可接受拼写（英美变体等）；判分时与 headword 一起接受，不自动放宽
    accepted_spellings: list[str] | None = Field(
        default=None, sa_column=Column("accepted_spellings", JSON, nullable=True)
    )
    example_en: str | None = Field(default=None, max_length=512)
    # 教师上传或已授权的标准音；为空时练习端用浏览器朗读兜底（需标注）
    audio_url: str | None = Field(default=None, max_length=1024)
    status: str = Field(default="active", max_length=16, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabularyBook(SQLModel, table=True):
    """词库：公共（管理员维护）或班级（教师自建）。版本化编辑不删旧任务。"""

    __tablename__ = "vocabulary_book"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=512)
    # public = 全体教师可用；classroom = 仅本班教师
    scope: str = Field(default="classroom", max_length=16, index=True)
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    # scope=classroom 时的所属课堂
    classroom_id: uuid.UUID | None = Field(
        default=None, foreign_key="classroom.id", ondelete="CASCADE", index=True
    )
    status: str = Field(default="active", max_length=16)
    version: int = Field(default=1, ge=1, sa_column_kwargs={"server_default": "1"})
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabularyBookItem(SQLModel, table=True):
    """词库有序内容；同一词库不重复收词。"""

    __tablename__ = "vocabulary_book_item"
    __table_args__ = (
        UniqueConstraint("book_id", "word_id", name="uq_vocab_book_word"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    book_id: uuid.UUID = Field(
        foreign_key="vocabulary_book.id", nullable=False, ondelete="CASCADE", index=True
    )
    word_id: uuid.UUID = Field(
        foreign_key="vocabulary_word.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    position: int = Field(default=0, ge=0)


class VocabularyAssignment(SQLModel, table=True):
    """课堂一次发布的词汇任务快照（对齐 ClassroomExercise 的快照体系）。

    词库后续编辑不影响已发布任务与学生历史报告；重发即新版本。
    """

    __tablename__ = "vocabulary_assignment"
    __table_args__ = (
        UniqueConstraint(
            "classroom_id", "version_no", name="uq_vocab_assignment_version"
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    title: str = Field(default="词汇练习", max_length=255)
    # practice = 可重试、首答计成绩；quiz = 一次提交（P1 落地，P0 只发练习）
    mode: str = Field(
        default="practice",
        max_length=16,
        sa_column_kwargs={"server_default": "practice"},
    )
    # 出题方式：meaning = 看义拼词；audio = 听音拼词（练习可用设备朗读兜底）
    prompt_types: list[str] = Field(
        default=lambda: ["meaning"], sa_column=Column("prompt_types", JSON)
    )
    # [{word_id, headword, part_of_speech, meaning_zh, meaning_en,
    #   accepted_spellings, audio_url, prompt_types}]
    snapshot_items: list[dict[str, object]] = Field(
        sa_column=Column("snapshot_items", JSON, nullable=False)
    )
    version_no: int = Field(default=1, ge=1)
    status: str = Field(default="published", max_length=16, index=True)
    # 测验（quiz）专用：个人时长（分钟）；开放/截止以服务器时间为准
    duration_minutes: int | None = Field(default=None, ge=5, le=240)
    # 及格线（百分制，score >= pass_line 即及格）；练习模式不用
    pass_line: int = Field(
        default=60, ge=0, le=100, sa_column_kwargs={"server_default": "60"}
    )
    # 成绩公布 / 答案公布分别控制（默认 None = 教师未公布）：
    # 未公布成绩前学生只能看到提交状态；未公布答案前不揭示拼写与对错
    grades_published_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    answers_published_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    opens_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    due_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    published_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    archived_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore


class VocabularyAssignmentTarget(SQLModel, table=True):
    """发布时固定的目标学生名单：完成率分母不随后续入班漂移。"""

    __tablename__ = "vocabulary_assignment_target"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_vocab_target_student"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    assignment_id: uuid.UUID = Field(
        foreign_key="vocabulary_assignment.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 教师单独授权一次补考的时间（默认一次参与；授权后允许第二轮答卷）
    retake_granted_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabularySession(SQLModel, table=True):
    """词汇练习轮次（与口语 PracticeSession 分表，互不影响）。

    一个学生对一个任务可有多个轮次：round_no=1 为首轮（任务成绩锁定首轮
    的首答），后续轮次为复习（「再练一轮」），独立记录不改写首轮成绩。

    kind 区分轮次来源：task = 教师任务（assignment_id 必有，题单读任务
    快照）；self = 词库自主练习；review = 错词专项复习。自主/复习轮的
    assignment_id 为空、题单固化在自身 snapshot_items（创建后不可变），
    不参与教师任务统计——练过相同词库不会自动完成教师任务。
    """

    __tablename__ = "vocabulary_session"
    __table_args__ = (
        # 同学生同任务同轮次唯一；并发「再练一轮」由唯一索引兜底
        Index(
            "ix_vocab_session_assignment_student_round",
            "assignment_id",
            "student_id",
            "round_no",
            unique=True,
            postgresql_where=text("assignment_id IS NOT NULL"),
        ),
        # 自主/复习轮 assignment_id 为空，不走上面的索引——并发开轮由两个
        # 部分唯一索引兜底：每学生每词库至多一个进行中自主轮、每学生至多
        # 一个进行中复习轮（轮次结束即退出索引谓词，不阻止开新一轮）
        Index(
            "uq_vocab_session_self_active",
            "student_id",
            "source_book_id",
            unique=True,
            postgresql_where=text(
                "assignment_id IS NULL AND kind = 'self' AND status = 'in_progress'"
            ),
        ),
        Index(
            "uq_vocab_session_review_active",
            "student_id",
            unique=True,
            postgresql_where=text(
                "assignment_id IS NULL AND kind = 'review' AND status = 'in_progress'"
            ),
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    assignment_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="vocabulary_assignment.id",
        ondelete="SET NULL",
        index=True,
    )
    # 轮次来源：task = 教师任务；self = 词库自主练习；review = 错词专项复习
    kind: str = Field(
        default="task", max_length=16, sa_column_kwargs={"server_default": "task"}
    )
    # kind=self 时的来源词库（review 无单一来源词库；历史报告展示用）
    source_book_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="vocabulary_book.id",
        ondelete="SET NULL",
    )
    # kind=self/review 的固定题单（条目结构与任务快照一致，另带 from_wrong
    # 标记）；创建后不可变，刷新/换端进入同一题单与题序
    snapshot_items: list[dict[str, object]] | None = Field(
        default=None, sa_column=Column("snapshot_items", JSON, nullable=True)
    )
    # kind=self 时是否按 30% 目标混入了历史错词
    mix_wrong: bool = Field(default=False, sa_column_kwargs={"server_default": "false"})
    mode: str = Field(
        default="practice",
        max_length=16,
        sa_column_kwargs={"server_default": "practice"},
    )
    # in_progress → submitted（全部题答过即完成；练习重试不回退状态）
    status: str = Field(
        default="in_progress",
        max_length=16,
        sa_column_kwargs={"server_default": "in_progress"},
    )
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    submitted_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore
    # 轮次序号：1=首轮（教师任务成绩），>1 为「再练一轮」的复习轮
    round_no: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    # 切屏计数（沿用模考思路；练习仅记录不启用，测验计入异常事件供教师判断）
    tab_switch_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # 测验个人计时起点：学生明确点「开始测验」才落（服务器时间，不随刷新/
    # 多端/客户端时间改变）；练习轮为空
    quiz_started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 终结方式：manual = 主动交卷；timeout = 到时服务端结算。status 仍为
    # submitted（终结态），教师端据此区分「已交卷 / 超时结束」
    end_reason: str | None = Field(default=None, max_length=16)


class VocabularyAnswer(SQLModel, table=True):
    """可审计的作答：原始输入 + 规范化结果 + 确定性判分。

    练习保留多次尝试（attempt_no 递增），教师统计与错词本默认看首答。
    """

    __tablename__ = "vocabulary_answer"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "item_index", "attempt_no", name="uq_vocab_answer_slot"
        ),
        UniqueConstraint("idempotency_key", name="uq_vocab_answer_idempotency_key"),
        Index("ix_vocab_answer_session_item", "session_id", "item_index"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(
        foreign_key="vocabulary_session.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    # 题号 = assignment.snapshot_items 下标（快照不可变，下标稳定）
    item_index: int = Field(ge=0)
    attempt_no: int = Field(default=1, ge=1)
    # meaning = 看义拼词；audio = 听音拼词
    prompt_type: str = Field(default="meaning", max_length=16)
    answer_raw: str = Field(max_length=255)
    answer_normalized: str = Field(max_length=255)
    is_correct: bool
    # 快照词标识（无外键：判分与展示永远按发布时内容，词库后续可归档）
    word_id: uuid.UUID = Field(index=True)
    # 答题时快照内容的冗余（错词本展示不再反查快照）
    headword: str = Field(max_length=64)
    meaning_zh: str = Field(max_length=255)
    answered_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    idempotency_key: str | None = Field(default=None, max_length=64)


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


class VocabularyAssignmentCreate(SQLModel):
    title: str | None = Field(default=None, max_length=255)
    # 二选一：整本词库（active 词）或显式词清单
    book_id: uuid.UUID | None = None
    word_ids: list[uuid.UUID] | None = None
    prompt_types: list[str] = ["meaning"]
    # practice = 可重试、首答计成绩；quiz = 限时测验（见发布校验）
    mode: str = "practice"
    # 测验参数：开放时间 / 截止时间（服务器时间口径）、个人时长（分钟）、
    # 及格线（百分制）。有效结束时间 = 个人开始 + 时长 与 due_at 较早者
    opens_at: datetime | None = None
    due_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=240)
    pass_line: int = Field(default=60, ge=0, le=100)


class VocabularyAssignmentPublic(SQLModel):
    id: uuid.UUID
    classroom_id: uuid.UUID
    title: str
    mode: str
    prompt_types: list[str] = []
    status: str
    version_no: int
    word_count: int
    due_at: datetime | None = None
    opens_at: datetime | None = None
    # 测验字段（练习模式为缺省值）
    duration_minutes: int | None = None
    pass_line: int = 60
    grades_published_at: datetime | None = None
    answers_published_at: datetime | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None
    created_by: uuid.UUID | None = None


class VocabularyQuizState(SQLModel):
    """学生侧测验状态：规则展示 + 个人计时 + 参与/公布进度。

    未开始也返回本对象（status=not_started），前端据此渲染规则页；
    剩余时间一律由服务器计算下发，客户端时间不可影响。
    """

    status: str  # not_started / in_progress / submitted / timed_out
    attempts_used: int = 0
    attempts_allowed: int = 1
    retake_granted: bool = False
    duration_minutes: int | None = None
    pass_line: int = 60
    opens_at: datetime | None = None
    due_at: datetime | None = None
    # in_progress：个人截止（min(开始+时长, due_at)）与剩余秒数
    started_at: datetime | None = None
    deadline: datetime | None = None
    remaining_seconds: int | None = None
    # 已终结：交卷时间与方式（manual=已交卷 / timeout=超时结束）
    submitted_at: datetime | None = None
    end_reason: str | None = None
    # 公布进度：未公布成绩前学生只能看到提交状态（score=None）
    score_visible: bool = False
    answers_visible: bool = False
    score: int | None = None
    passed: bool | None = None
    tab_switch_count: int = 0


class VocabularyTodayItem(SQLModel):
    """学生题单条目：未作答的词不透露拼写（headword=None）。"""

    item_index: int
    prompt_type: str
    part_of_speech: str | None = None
    meaning_zh: str
    meaning_en: str | None = None
    audio_url: str | None = None
    # 已答（首答存在）才回填拼写与对错
    headword: str | None = None
    answered: bool = False
    is_correct: bool | None = None
    attempt_count: int = 0


class VocabularyStudentAssignment(SQLModel):
    """学生任务列表条目：进度与时间（逾期）两维分别展示。"""

    assignment_id: uuid.UUID
    title: str
    word_count: int
    due_at: datetime | None = None
    # 进度维度：not_started / in_progress / completed
    progress: str = "not_started"
    # 时间维度（独立于进度）：now > due_at 且任务未完成
    overdue: bool = False
    answered_count: int = 0
    correct_first_count: int = 0
    round_count: int = 1
    # 测验且成绩未公布：correct_first_count 置 0 不下发，前端隐藏成绩维度
    masked: bool = False
    # 测验标记（前端区分练习/测验展示）
    is_quiz: bool = False


class VocabularyRoundSummaryRow(SQLModel):
    """学生侧轮次摘要：轮次回看入口（只读查看指定轮）。

    测验成绩未公布时 masked=True：correct_first_count 置 0 不下发。
    """

    round_no: int
    status: str  # in_progress / submitted
    answered_count: int
    correct_first_count: int
    submitted_at: datetime | None = None
    masked: bool = False
    # 测验答卷终结方式：manual=已交卷 / timeout=超时结束
    end_reason: str | None = None


class VocabularyTodayPlan(SQLModel):
    """GET /classes/{code}/vocabulary/today 的学生视图。"""

    assignment: VocabularyAssignmentPublic | None = None
    session_id: uuid.UUID | None = None
    session_status: str | None = None
    # 展示轮的轮号（round_no 参数指定的回看轮，缺省=当前可练轮）
    session_round: int | None = None
    # 当前可练轮（未结束轮优先，否则最新轮；独立于展示轮参数）——
    # 前端据此判定「回看的是不是当前轮」，不能拿展示轮自比
    current_round: int | None = None
    # 任务级作答门禁原因（独立于会话状态，未开始/进行中/已完成统一计算）：
    # due_passed / archived；任务开放作答为 None
    session_closed_reason: str | None = None
    items: list[VocabularyTodayItem] = []
    answered_count: int = 0
    correct_first_count: int = 0
    wrong_word_count: int = 0
    # 测验状态（practice 任务为 None）；items 的揭示规则受其公布字段约束
    quiz: VocabularyQuizState | None = None
    # 聚焦任务的全部轮次摘要（回看入口；items 展示哪一轮由 round_no 参数决定）
    rounds: list[VocabularyRoundSummaryRow] = []
    # 名单内全部任务（按 due 升序、无 due 按发布倒序）
    assignments: list[VocabularyStudentAssignment] = []


class VocabularySessionCreate(SQLModel):
    """创建/恢复作答会话：缺省 assignment_id = 聚焦任务。"""

    assignment_id: uuid.UUID | None = None
    # round="new"：全部轮次已结束时开新的复习轮（round_no=max+1）；
    # continue/缺省=续做未结束轮（全结后 422，不新建）
    round: str | None = Field(default=None, max_length=8)


class VocabularyAnswerRequest(SQLModel):
    item_index: int = Field(ge=0)
    prompt_type: str = Field(default="meaning", max_length=16)
    answer: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)


class VocabularyAnswerResult(SQLModel):
    item_index: int
    attempt_no: int
    is_correct: bool
    # 标准拼写（首答后即揭示；练习重试对错即时反馈）
    correct_spelling: str
    meaning_zh: str
    session_status: str
    answered_count: int
    correct_first_count: int


class VocabularyQuizAnswerReceipt(SQLModel):
    """测验作答回执：只确认已接收，不返回答案与正误（防提前泄露）。"""

    item_index: int
    received: bool = True
    answered_count: int
    session_status: str
    # 服务器计算的剩余秒数（客户端倒计时只是展示）
    remaining_seconds: int | None = None


class VocabularyStudentRoundRow(SQLModel):
    """单个轮次的独立汇总（首轮=任务成绩；复习轮单独记录）。

    测验成绩未公布时 masked=True：correct_first_count 置 0 不下发。
    """

    round_no: int
    status: str  # in_progress / submitted
    answered_count: int
    correct_first_count: int
    submitted_at: datetime | None = None
    masked: bool = False
    # 测验答卷终结方式：manual=已交卷 / timeout=超时结束
    end_reason: str | None = None


class VocabularyStudentResultRow(SQLModel):
    """教师结果面板的学生行（按目标名单，含未开始）。

    任务成绩锁定首轮（round_no=1 的首答）；rounds 为各轮次独立汇总，
    供教师查看复习轮，不参与完成度与正确率统计。
    """

    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    status: str  # not_started / in_progress / completed
    answered_count: int
    correct_first_count: int
    total_count: int
    submitted_at: datetime | None = None
    round_count: int = 0
    rounds: list[VocabularyStudentRoundRow] = []
    # ── 测验扩展（practice 任务为缺省值）──
    # 终结方式：None=未结束，manual=已交卷，timeout=超时结束
    quiz_end_reason: str | None = None
    # 百分制成绩（correct/total，未答计 0）；参与次数 = 已开考的答卷数
    score: int | None = None
    passed: bool | None = None
    # 有效成绩来自哪一份答卷（最好整卷，同分取较早轮）；None=尚无终结答卷
    effective_round_no: int | None = None
    tab_switch_count: int = 0
    retake_granted: bool = False
    attempt_count: int = 0


class VocabularyWordMisspelling(SQLModel):
    answer: str
    count: int


class VocabularyWordStatRow(SQLModel):
    """逐词错误分布（教师据此安排复习）。"""

    item_index: int
    word_id: uuid.UUID
    headword: str
    meaning_zh: str
    answered_count: int
    correct_first_count: int
    error_count: int
    misspellings: list[VocabularyWordMisspelling] = []


class VocabularyClassResults(SQLModel):
    """GET /classes/{code}/vocabulary/results。"""

    assignment: VocabularyAssignmentPublic | None = None
    target_count: int = 0
    completed_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    students: list[VocabularyStudentResultRow] = []
    words: list[VocabularyWordStatRow] = []
    # ── 测验扩展 ──
    # timed_out（超时结束）单列统计；及格/公布进度与平均分（已交卷口径）
    timed_out_count: int = 0
    pass_line: int | None = None
    passed_count: int = 0
    avg_score: int | None = None
    grades_published: bool = False
    answers_published: bool = False


class VocabularyTeacherAssignmentRow(SQLModel):
    """教师任务列表行：任务 + 名单进度汇总（首轮首答口径，逾期独立计数）。"""

    assignment: VocabularyAssignmentPublic
    target_count: int = 0
    completed_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    overdue_count: int = 0


class VocabularyWrongWordItem(SQLModel):
    """错词本条目：首答判错的词，按快照内容展示。

    三个维度分开、互不改写：wrong_count 只增不减（一次答对不删除错词、
    不冲抵历史错误次数）；last_first_* 是最近一次独立首答（每轮第一次
    作答）的结果；last_correct_at 是最近一次答对时间。不是科学掌握度
    评估，只用于安排复习。
    """

    word_id: uuid.UUID
    headword: str
    meaning_zh: str
    part_of_speech: str | None = None
    wrong_count: int
    last_wrong_at: datetime | None = None
    # 最近独立首答（attempt_no=1）的时间与对错；从未复盘过为 None
    last_first_at: datetime | None = None
    last_first_is_correct: bool | None = None
    # 最近一次答对的时间（任意尝试；从未答对为 None）
    last_correct_at: datetime | None = None
    # 词条是否仍在当前可练词库（active 公共库/本班库）内；不在则不能进复习
    practiceable: bool = True


class VocabularyWrongWords(SQLModel):
    classroom_code: str
    items: list[VocabularyWrongWordItem] = []


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


# ── 学生自主练习与学习报告（词库浏览 / 自主开轮 / 历史趋势）────────

SELF_PRACTICE_DEFAULT_WORDS = 20

SELF_PRACTICE_MAX_WORDS = 100

SELF_PRACTICE_MIX_WRONG_RATIO = 0.3


class VocabularyStudentSessionCreate(SQLModel):
    """学生自主开轮请求：kind=self 从词库选题，kind=review 练历史错词。"""

    kind: str = "self"
    # kind=self 必填；kind=review 忽略该参数
    book_id: uuid.UUID | None = None
    # 目标词数：词库/错词不足时按实际数量出题（开始前明确展示实际数量）
    word_count: int = Field(default=SELF_PRACTICE_DEFAULT_WORDS, ge=1)
    # 仅 kind=self：按 30% 目标混入所选词库内的历史错词（最近错误优先）
    mix_wrong: bool = False


class VocabularyStudentSessionCreated(SQLModel):
    session_id: uuid.UUID
    kind: str
    title: str
    book_id: uuid.UUID | None = None
    total_count: int
    # 混入的历史错词数（kind=self 且 mix_wrong 时 > 0；review = 全部）
    wrong_word_count: int = 0
    started_at: datetime | None = None


class VocabularyStudentItem(VocabularyTodayItem):
    """自主练习/历史详情的题单条目（在任务题单结构上加来源与本人首答）。"""

    # 是否选自历史错词（self+mix_wrong 混入的词 / review 全部词条）
    from_wrong: bool = False
    # 本人首次作答的原始输入（已答才返回；未答不透露任何拼写）
    first_answer: str | None = None


class VocabularyStudentPlan(SQLModel):
    """GET /vocabulary/student/sessions/{id}：自主练习作答与单次详情视图。

    兼容三类轮次（task/self/review）：题单口径一致——未答题不透露拼写；
    首答正确率分母为已答题数（前端计算），完成进度分母为 total_count。
    测验答卷受公布规则约束：answers_visible=False 时已答题也不揭示
    拼写与对错（first_answer 仍回填本人输入）；score_visible=False 时
    correct_first_count 置 0 不下发（masked 提示前端隐藏成绩维度）。
    """

    session_id: uuid.UUID
    kind: str
    status: str  # in_progress / submitted
    title: str
    book_id: uuid.UUID | None = None
    round_no: int | None = None
    mix_wrong: bool = False
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    total_count: int = 0
    answered_count: int = 0
    correct_first_count: int = 0
    items: list[VocabularyStudentItem] = []
    # ── 测验扩展（非测验轮为缺省值）──
    is_quiz: bool = False
    end_reason: str | None = None
    deadline: datetime | None = None
    remaining_seconds: int | None = None
    answers_visible: bool = True
    score_visible: bool = True
    masked: bool = False


class VocabularyStudentHistoryRow(SQLModel):
    """练习历史行：一次轮次一行，kind 区分教师任务/自主练习/错词复习。

    正确率口径在行内不自算（避免画成能力成绩）：前端用
    correct_first_count / answered_count 展示首答正确率，零作答显示未作答。
    测验成绩未公布时 masked=True：correct_first_count 置 0 不下发，
    前端只展示提交状态（已交卷 / 进行中 / 超时结束）。
    """

    session_id: uuid.UUID
    kind: str
    title: str
    status: str
    round_no: int | None = None
    total_count: int = 0
    answered_count: int = 0
    correct_first_count: int = 0
    started_at: datetime | None = None
    submitted_at: datetime | None = None
    book_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    masked: bool = False
    is_quiz: bool = False
    end_reason: str | None = None


class VocabularyStudentHistory(SQLModel):
    items: list[VocabularyStudentHistoryRow] = []


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
