"""词汇模型：数据库表模型（背单词 7 张表）（拆分自 app/models/vocabulary.py，2026-11-07）。"""

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
