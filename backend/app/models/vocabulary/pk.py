"""词汇第三批：课堂实时 PK 独立表与接口 schema。

边界（设计稿 `docs/vocabulary-pk-farm-design-20261122.md` §2/§3）：

- 班内、自愿、不跨校公开：大厅/对局/作答只对本课堂成员与本班教师可见；
  学生必须显式加入，未参与不影响教师任务完成度。
- 口径分离：PK 作答只落本表，**不写 ``VocabularyAnswer``、不改任务首答
  统计、不动任何发布快照**；教师结果页不混入 PK 数据。
- 题单在开大厅时固化进 ``snapshot_items``（复用四题型与快照构建），对局
  双方题面/选项/挖空/语素块完全一致；之后改词库不影响进行中的对局。
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.models.base import _tenant_id_field, get_datetime_utc

# ── 容量口径（设计稿 §1.3，可验收）─────────────────────────────────
MAX_QUEUE_PLAYERS = 20  # 同时排队/对局上限（10 场 1v1）
MAX_ACTIVE_MATCHES = 10
DEFAULT_QUESTION_COUNT = 8
DEFAULT_PER_QUESTION_SECONDS = 20
MAX_QUESTION_COUNT = 20
MIN_PER_QUESTION_SECONDS = 1
MAX_PER_QUESTION_SECONDS = 60

# 判分口径（§3）：正确 +100 基础分，速度奖励 0–50；错答 0。
PK_ANSWER_BASE = 100
PK_SPEED_BONUS_MAX = 50

# 对局状态
PK_LOBBY_OPEN = "open"
PK_LOBBY_CLOSED = "closed"
PLAYER_WAITING = "waiting"
PLAYER_ACTIVE = "active"
PLAYER_FINISHED = "finished"
PLAYER_LEFT = "left"
MATCH_ACTIVE = "active"
MATCH_FINISHED = "finished"
MATCH_ABANDONED = "abandoned"


class VocabPkLobby(SQLModel, table=True):
    """本班一个 PK 大厅：词库/题量/限时与固化题单。

    同一课堂同时至多一个开放大厅；关闭后历史大厅与对局保留供回看。
    """

    __tablename__ = "vocab_pk_lobby"
    # 同一课堂至多一个开放大厅；历史关闭大厅可多条（部分唯一索引）
    __table_args__ = (
        Index(
            "uq_vocab_pk_lobby_open",
            "classroom_id",
            unique=True,
            postgresql_where=text(f"status = '{PK_LOBBY_OPEN}'"),
        ),
    )
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    book_id: uuid.UUID | None = Field(
        default=None, foreign_key="vocabulary_book.id", ondelete="SET NULL", index=True
    )
    prompt_types: list[str] = Field(
        default_factory=lambda: ["meaning"],
        sa_column=Column("prompt_types", JSON, nullable=False),
    )
    question_count: int = Field(default=DEFAULT_QUESTION_COUNT, ge=1)
    per_question_seconds: int = Field(default=DEFAULT_PER_QUESTION_SECONDS, ge=1)
    status: str = Field(default=PK_LOBBY_OPEN, max_length=16)
    # 开大厅时固化的题单（条目结构与任务快照一致，另含题型专属载荷）；
    # 创建后不可变，对局双方共用同一份
    snapshot_items: list[dict[str, object]] = Field(
        sa_column=Column("snapshot_items", JSON, nullable=False)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    closed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabPkMatch(SQLModel, table=True):
    """一场 1v1 对局：题单副本、服务端时钟、比分与结算口径。

    计时一律以服务端时间为准：``current_deadline_at`` 是当前题的截止点；
    断线重连按 ``match_id`` 恢复当前题、剩余时间与比分。
    """

    __tablename__ = "vocab_pk_match"
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lobby_id: uuid.UUID = Field(
        foreign_key="vocab_pk_lobby.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    snapshot_items: list[dict[str, object]] = Field(
        sa_column=Column("snapshot_items", JSON, nullable=False)
    )
    question_count: int = Field(ge=1)
    per_question_seconds: int = Field(ge=1)
    status: str = Field(default=MATCH_ACTIVE, max_length=16)
    # 当前题下标（双方各自作答进度独立，此处为对局公共的下一题推进参考）
    current_item_index: int = Field(default=0, ge=0)
    current_deadline_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    end_reason: str | None = Field(default=None, max_length=16)
    # 结算：总分高者胜；同分比总用时（total_seconds 小者胜）
    winner_student_id: uuid.UUID | None = Field(default=None, index=True)
    # 状态版本号：每次状态变更自增，SSE 推送版本变化，前端与轮询读同一快照
    state_version: int = Field(default=1)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabPkPlayer(SQLModel, table=True):
    """大厅排队成员 / 对局玩家。一局两侧 left/right。"""

    __tablename__ = "vocab_pk_player"
    __table_args__ = (
        UniqueConstraint(
            "lobby_id", "student_id", name="uq_vocab_pk_player_lobby_student"
        ),
    )
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    lobby_id: uuid.UUID = Field(
        foreign_key="vocab_pk_lobby.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    match_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="vocab_pk_match.id",
        ondelete="SET NULL",
        index=True,
    )
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    side: str | None = Field(default=None, max_length=8)
    status: str = Field(default=PLAYER_WAITING, max_length=16)
    score: int = Field(default=0, ge=0)
    answered_count: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    # 总用时（秒，浮点）：同分胜负口径，累计每题作答时延
    total_seconds: float = Field(default=0.0, ge=0)
    joined_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    left_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabPkAnswer(SQLModel, table=True):
    """PK 作答记录：独立于 ``VocabularyAnswer``，不参与任务统计。

    每题只计首次有效提交；幂等键全局唯一，断网重传同键返回首次结果，
    不二次计分。
    """

    __tablename__ = "vocab_pk_answer"
    __table_args__ = (
        UniqueConstraint("player_id", "item_index", name="uq_vocab_pk_answer_slot"),
        UniqueConstraint("idempotency_key", name="uq_vocab_pk_answer_idempotency"),
    )
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    match_id: uuid.UUID = Field(
        foreign_key="vocab_pk_match.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    player_id: uuid.UUID = Field(
        foreign_key="vocab_pk_player.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    item_index: int = Field(ge=0)
    prompt_type: str = Field(default="meaning", max_length=16)
    answer_raw: str = Field(max_length=255)
    answer_normalized: str = Field(max_length=255)
    is_correct: bool
    base_score: int = Field(default=0, ge=0)
    speed_bonus: int = Field(default=0, ge=0)
    score: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    answered_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    idempotency_key: str | None = Field(default=None, max_length=64)


# ── 接口 schema（非表）─────────────────────────────────────────────


class PkLobbyCreate(SQLModel):
    """教师开大厅：选词库；题量/限时/题型可演示默认值。"""

    book_id: uuid.UUID
    question_count: int | None = Field(default=None, ge=1, le=MAX_QUESTION_COUNT)
    per_question_seconds: int | None = Field(
        default=None, ge=MIN_PER_QUESTION_SECONDS, le=MAX_PER_QUESTION_SECONDS
    )
    prompt_types: list[str] | None = None


class PkPlayerSummary(SQLModel):
    student_id: uuid.UUID
    display_name: str | None = None
    side: str | None = None
    status: str
    score: int = 0
    answered_count: int = 0
    correct_count: int = 0
    total_seconds: float = 0.0
    # 所属对局；等待中为 None。教师端大厅视图按它分组进行中对局。
    match_id: uuid.UUID | None = None


class PkLobbyView(SQLModel):
    lobby_id: uuid.UUID | None = None
    status: str | None = None
    book_id: uuid.UUID | None = None
    question_count: int = DEFAULT_QUESTION_COUNT
    per_question_seconds: int = DEFAULT_PER_QUESTION_SECONDS
    prompt_types: list[str] = []
    queue_count: int = 0
    active_match_count: int = 0
    # 当前访问者在大厅中的状态：waiting / active / left / None（未加入）
    my_status: str | None = None
    my_match_id: uuid.UUID | None = None
    players: list[PkPlayerSummary] = []
    created_at: datetime | None = None
    closed_at: datetime | None = None


class PkChoice(SQLModel):
    word_id: uuid.UUID
    headword: str
    meaning_zh: str
    part_of_speech: str | None = None
    is_answer: bool = False


class PkMorphSegment(SQLModel):
    text: str
    gloss: str
    kind: str


class PkMatchItem(SQLModel):
    """对局题面条目：字段对齐前端 PromptBody 既有口径。"""

    item_index: int
    prompt_type: str
    part_of_speech: str | None = None
    meaning_zh: str
    meaning_en: str | None = None
    audio_url: str | None = None
    choices: list[PkChoice] = []
    cloze_sentence: str | None = None
    morph_segments: list[PkMorphSegment] = []
    # 本人已答后回填拼写与对错；未答不透露 headword
    headword: str | None = None
    answered: bool = False
    is_correct: bool | None = None
    first_choice_word_id: uuid.UUID | None = None
    score: int | None = None


class PkMatchResult(SQLModel):
    status: str
    end_reason: str | None = None
    winner_student_id: uuid.UUID | None = None
    # 平局（同分同时长）时为 None
    drew: bool = False


class PkMatchView(SQLModel):
    match_id: uuid.UUID
    lobby_id: uuid.UUID
    status: str
    state_version: int
    question_count: int
    current_item_index: int
    remaining_seconds: int | None = None
    per_question_seconds: int = DEFAULT_PER_QUESTION_SECONDS
    me: PkPlayerSummary
    opponent: PkPlayerSummary | None = None
    items: list[PkMatchItem] = []
    result: PkMatchResult | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PkAnswerRequest(SQLModel):
    item_index: int = Field(ge=0)
    prompt_type: str = Field(default="meaning", max_length=16)
    answer: str = Field(min_length=1, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)


class PkAnswerResult(SQLModel):
    item_index: int
    is_correct: bool
    base_score: int
    speed_bonus: int
    score: int
    answered_count: int
    correct_count: int
    my_score: int
    match_status: str
    remaining_seconds: int | None = None
    # 幂等重放命中时为 True：返回的是首次结果，未二次计分
    replayed: bool = False
