"""词汇第三批补充：课堂大屏 PK「房间码」形态的独立表与接口 schema。

与既有 1v1 排队 PK（`pk.py`）并存、互不影响：

- 教师开房即生成 6 位房间码，学生凭码入场，全班同题序、同一服务端时钟；
- 两种赛制：`solo` 全班个人计分 / `team` 小组阵营（入场时按人数均分）；
- 主持端只读大屏（当前题、倒计时、正确率分布、队伍积分、结算排名）。

口径（沿用设计稿 §2 隔离原则）：房间作答只落 `vocab_pk_room_answer`，不写
`VocabularyAnswer`、不改任务统计、不写错词本、不进 FSRS。
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import _tenant_id_field, get_datetime_utc

# ── 容量与口径 ────────────────────────────────────────────────────
ROOM_CODE_LENGTH = 6
MAX_ROOM_PLAYERS = 60
MAX_TEAM_COUNT = 6
MIN_TEAM_COUNT = 2
DEFAULT_ROOM_QUESTION_COUNT = 10
DEFAULT_ROOM_SECONDS = 20

# 房间状态
ROOM_WAITING = "waiting"
ROOM_LIVE = "live"
ROOM_ENDED = "ended"

# 赛制
ROOM_MODE_SOLO = "solo"
ROOM_MODE_TEAM = "team"


class VocabPkRoom(SQLModel, table=True):
    """一次课堂大屏 PK：房间码、固化题单、服务端时钟与赛制。

    题单在开房时固化（与任务发布同口径），之后改词库不影响进行中的班级赛。
    题目推进由 `started_at + 题序 * 单题秒数` 推导，无后台任务，断线重连
    直接按服务端时间算回当前题与剩余秒数。
    """

    __tablename__ = "vocab_pk_room"
    __table_args__ = (
        # 房间码全局唯一：6 位码不回收，避免旧码误入新房间
        UniqueConstraint("room_code", name="uq_vocab_pk_room_code"),
        Index("ix_vocab_pk_room_class_status", "classroom_id", "status"),
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
    room_code: str = Field(max_length=ROOM_CODE_LENGTH)
    mode: str = Field(default=ROOM_MODE_SOLO, max_length=8)
    # 仅 team 赛制有意义；solo 时为 0
    team_count: int = Field(default=0, ge=0)
    prompt_types: list[str] = Field(
        default_factory=lambda: ["meaning"],
        sa_column=Column("prompt_types", JSON, nullable=False),
    )
    question_count: int = Field(default=DEFAULT_ROOM_QUESTION_COUNT, ge=1)
    per_question_seconds: int = Field(default=DEFAULT_ROOM_SECONDS, ge=1)
    status: str = Field(default=ROOM_WAITING, max_length=16)
    snapshot_items: list[dict[str, object]] = Field(
        sa_column=Column("snapshot_items", JSON, nullable=False)
    )
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    ended_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabPkRoomPlayer(SQLModel, table=True):
    """房间参赛者：座位号、所属队伍与累计比分（入场即建，未答不扣分）。"""

    __tablename__ = "vocab_pk_room_player"
    __table_args__ = (
        UniqueConstraint(
            "room_id", "student_id", name="uq_vocab_pk_room_player_room_student"
        ),
    )
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    room_id: uuid.UUID = Field(
        foreign_key="vocab_pk_room.id", nullable=False, ondelete="CASCADE", index=True
    )
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    # solo 为 0；team 为 1..team_count
    team_index: int = Field(default=0, ge=0)
    score: int = Field(default=0, ge=0)
    answered_count: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    total_seconds: float = Field(default=0.0, ge=0)
    joined_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class VocabPkRoomAnswer(SQLModel, table=True):
    """房间作答：每人每题只计首次有效提交（重复提交返回首次结果）。

    独立于 `vocab_pk_answer`（1v1）与 `vocab_answer`（任务），互不写入。
    """

    __tablename__ = "vocab_pk_room_answer"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "item_index", name="uq_vocab_pk_room_answer_slot"
        ),
    )
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    room_id: uuid.UUID = Field(
        foreign_key="vocab_pk_room.id", nullable=False, ondelete="CASCADE", index=True
    )
    player_id: uuid.UUID = Field(
        foreign_key="vocab_pk_room_player.id",
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
    is_correct: bool
    base_score: int = Field(default=0, ge=0)
    speed_bonus: int = Field(default=0, ge=0)
    score: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    answered_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# ── 接口 schema（非表）─────────────────────────────────────────────


class PkRoomCreate(SQLModel):
    """教师开房：选词库、题量/限时/题型与赛制。"""

    book_id: uuid.UUID
    question_count: int | None = Field(default=None, ge=1, le=20)
    per_question_seconds: int | None = Field(default=None, ge=1, le=60)
    prompt_types: list[str] | None = None
    mode: str = Field(default=ROOM_MODE_SOLO, max_length=8)
    team_count: int | None = Field(default=None, ge=MIN_TEAM_COUNT, le=MAX_TEAM_COUNT)


class PkRoomJoin(SQLModel):
    """学生凭 6 位码入场。"""

    code: str = Field(min_length=ROOM_CODE_LENGTH, max_length=ROOM_CODE_LENGTH)


class PkRoomAnswerRequest(SQLModel):
    item_index: int = Field(ge=0)
    prompt_type: str = Field(default="meaning", max_length=16)
    answer: str = Field(min_length=1, max_length=255)


class PkRoomPlayerSummary(SQLModel):
    student_id: uuid.UUID
    display_name: str | None = None
    team_index: int = 0
    score: int = 0
    answered_count: int = 0
    correct_count: int = 0
    total_seconds: float = 0.0
    rank: int | None = None
    answered_current: bool = False


class PkRoomTeamSummary(SQLModel):
    team_index: int
    label: str
    score: int = 0
    member_count: int = 0
    answered_count: int = 0
    correct_count: int = 0


class PkRoomQuestionStats(SQLModel):
    item_index: int
    prompt_type: str
    answered_count: int = 0
    correct_count: int = 0
    # 正确率 0–1；无人作答为 None（不折算 0%）
    accuracy: float | None = None
    headword: str | None = None
    meaning_zh: str | None = None


class PkRoomResultRow(SQLModel):
    team_index: int = 0
    label: str
    score: int
    rank: int
    member_count: int = 0


class PkRoomResult(SQLModel):
    """结算：队伍/个人排名、每题正确率与易错词清单（只读，不回流任务）。"""

    teams: list[PkRoomResultRow] = []
    players: list[PkRoomPlayerSummary] = []
    questions: list[PkRoomQuestionStats] = []
    wrong_words: list[str] = []


class PkRoomItem(SQLModel):
    """当前题面：本人未答时不透露 headword。"""

    item_index: int
    prompt_type: str
    part_of_speech: str | None = None
    meaning_zh: str = ""
    meaning_en: str | None = None
    choices: list[dict[str, object]] = []
    cloze_sentence: str | None = None
    morph_segments: list[dict[str, object]] = []
    headword: str | None = None
    answered: bool = False
    is_correct: bool | None = None
    score: int | None = None


class PkRoomHostView(SQLModel):
    room_id: uuid.UUID
    room_code: str
    classroom_id: uuid.UUID
    book_id: uuid.UUID | None = None
    status: str
    mode: str
    team_count: int = 0
    question_count: int
    per_question_seconds: int
    prompt_types: list[str] = []
    # 当前题序（从 0 起）；已结束等于 question_count
    current_item_index: int = 0
    remaining_seconds: int = 0
    participant_count: int = 0
    # 当前题已答/答对人数
    current_answered_count: int = 0
    current_correct_count: int = 0
    current_accuracy: float | None = None
    current_item: PkRoomQuestionStats | None = None
    players: list[PkRoomPlayerSummary] = []
    teams: list[PkRoomTeamSummary] = []
    questions: list[PkRoomQuestionStats] = []
    started_at: datetime | None = None
    ended_at: datetime | None = None
    result: PkRoomResult | None = None


class PkRoomStudentView(SQLModel):
    room_id: uuid.UUID
    room_code: str
    status: str
    mode: str
    team_count: int = 0
    question_count: int
    per_question_seconds: int
    current_item_index: int = 0
    remaining_seconds: int = 0
    item: PkRoomItem | None = None
    me: PkRoomPlayerSummary | None = None
    participants: int = 0
    teams: list[PkRoomTeamSummary] = []
    result: PkRoomResult | None = None


class PkRoomAnswerResult(SQLModel):
    item_index: int
    is_correct: bool
    score: int
    base_score: int = 0
    speed_bonus: int = 0
    headword: str | None = None
    my_score: int = 0
    rank: int | None = None
