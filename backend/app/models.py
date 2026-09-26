import uuid
from datetime import UTC, date, datetime

from pydantic import EmailStr
from sqlalchemy import JSON, Column, Date, DateTime
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# ── 口语评测（第 2 周范围：课堂码 + 分级问答）────────────────────────
# PRD §8.4 功能树：内容（篇目/复述句/情景/词表档）、课堂（课堂码/显示名/练习会话）、
# 作答（录音/转写/分数/建议）。词表档是第 3 周内容，暂不建。


class PassageBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(default="Pets", max_length=100)
    cefr_band: str = Field(default="B1", max_length=10)
    text: str = Field(min_length=1)
    # 标准音地址；为空时前端用 speechSynthesis 兜底（PRD §7.2）
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=45, ge=10, le=180)
    is_active: bool = True


class Passage(PassageBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=100)
    # 所属学习单元（关卡）；为空时挂全局默认（老数据兼容）
    unit_id: uuid.UUID | None = Field(
        default=None, foreign_key="unit.id", ondelete="SET NULL"
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class PassagePublic(PassageBase):
    id: uuid.UUID
    slug: str
    created_at: datetime | None = None


class PassageCreate(PassageBase):
    slug: str = Field(min_length=1, max_length=100)
    unit_id: uuid.UUID | None = None


# 学习单元（EIP 教材单元 → 学生端关卡地图）；顺序解锁 + 老师可全开
class Unit(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_index: int = Field(default=0, ge=0, index=True)
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(max_length=100)
    is_active: bool = True


class UnitPublic(SQLModel):
    id: uuid.UUID
    order_index: int
    title: str
    topic: str
    is_active: bool


class UnitCreate(SQLModel):
    order_index: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=255)
    topic: str = Field(max_length=100)
    is_active: bool = True


class UnitUpdate(SQLModel):
    order_index: int | None = None
    title: str | None = None
    topic: str | None = None
    is_active: bool | None = None


# 听后复述句：属于篇目，由短到长排序（PRD §6：一轮 3 句）
class RepeatSentence(SQLModel, table=True):
    __tablename__ = "repeat_sentence"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    passage_id: uuid.UUID = Field(
        foreign_key="passage.id", nullable=False, ondelete="CASCADE"
    )
    order_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=8, ge=3, le=60)


# 情景主题（来自 EIP），同主题一组问法分属低/中/高档（PRD §8.4）
class Scenario(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    topic: str = Field(unique=True, index=True, max_length=100)
    is_active: bool = True


# 分级词表（PRD §8.4：词条、词元、CEFR 档；学校 CSV 替换内置演示词表）
class WordlistEntry(SQLModel, table=True):
    __tablename__ = "wordlist_entry"

    id: int | None = Field(default=None, primary_key=True)
    lemma: str = Field(unique=True, index=True, max_length=64)
    band: str = Field(max_length=10, index=True)


class ScenarioQuestion(SQLModel, table=True):
    __tablename__ = "scenario_question"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scenario_id: uuid.UUID = Field(
        foreign_key="scenario.id", nullable=False, ondelete="CASCADE"
    )
    # 档位与篇目 cefr_band 同一套值：A2 / B1 / B2
    band: str = Field(max_length=10, index=True)
    order_index: int = Field(default=0, ge=0)
    text: str = Field(min_length=1)
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=20, ge=10, le=60)


class ScenarioQuestionPublic(SQLModel):
    id: uuid.UUID
    band: str
    text: str
    audio_url: str | None = None
    suggested_seconds: int


# 课堂码即弱密码（PRD §8.5）：无账号体系，泄露只影响一个班的成绩可见性
class Classroom(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, max_length=16)
    class_size: int = Field(default=40, ge=1, le=100)
    is_active: bool = True
    # 老师一键解锁全部关卡（默认顺序解锁）
    unlock_all: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ClassroomPublic(SQLModel):
    id: uuid.UUID
    code: str
    class_size: int
    is_active: bool
    unlock_all: bool = False
    created_at: datetime | None = None


class ClassroomCreate(SQLModel):
    class_size: int = Field(default=40, ge=1, le=100)


# 学生：显示名 + 同名 4 位区分码；无正式账号（PRD US-04）
class Student(SQLModel, table=True):
    __tablename__ = "student"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE"
    )
    display_name: str = Field(min_length=1, max_length=64)
    # 同名时追加的 4 位区分码，展示给学生（PRD US-04）
    suffix: str | None = Field(default=None, max_length=4)
    # 当前练习档：A2 / B1 / B2。学生端不展示升降，只换题（PRD §6）
    current_band: str = Field(default="B1", max_length=10)
    # 激励层（只和自己比）：经验值 / 连胜天数 / 最近练习日
    xp: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    streak_days: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    last_practice_date: date | None = Field(default=None, sa_type=Date)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# 徽章发放记录；定义见 app/scoring/gamification.py 的 BADGES 常量
class StudentBadge(SQLModel, table=True):
    __tablename__ = "student_badge"

    id: int | None = Field(default=None, primary_key=True)
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    badge_key: str = Field(max_length=32, index=True)
    awarded_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class StudentJoin(SQLModel):
    display_name: str = Field(min_length=1, max_length=64)


class StudentPublic(SQLModel):
    id: uuid.UUID
    display_name: str
    suffix: str | None = None
    current_band: str
    classroom_id: uuid.UUID


# 一次练习会话：一个学生一天一轮（PRD §8.4：日期、当前档、做到哪一题）
class PracticeSession(SQLModel, table=True):
    __tablename__ = "practice_session"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE"
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE"
    )
    # 本轮开始时的档位；问答档位见 question_band
    band: str = Field(max_length=10)
    # 3 句复述做完后按规则调整出的问答档位（PRD US-05：跟读结果定问答档）
    question_band: str | None = Field(default=None, max_length=10)
    # 本轮星级（0-3，完成即 ≥1）；结算见 gamification.settle_session
    stars: int | None = Field(default=None)
    # 本轮练习的篇目（关卡进度按 passage → unit 聚合）
    passage_id: uuid.UUID | None = Field(
        default=None, foreign_key="passage.id", ondelete="SET NULL"
    )
    session_date: date = Field(sa_type=Date)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# 作答状态机：上传即返回 queued，后台评分线程推进到 done/failed。
# PRD 不可协商 #4：上传成功与评分完成分离，学生不等待云端评分。
class AttemptStatus:
    QUEUED = "queued"
    SCORING = "scoring"
    DONE = "done"
    FAILED = "failed"


class AttemptItemType:
    PASSAGE = "passage"
    REPEAT = "repeat"
    QUESTION = "question"


class Attempt(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 作答对象：passage（MVP 整篇跟读）/ repeat（复述句）/ question（情景问答）
    item_type: str = Field(default=AttemptItemType.PASSAGE, max_length=16, index=True)
    item_id: uuid.UUID = Field(index=True)
    student_id: uuid.UUID | None = Field(
        default=None, foreign_key="student.id", ondelete="CASCADE"
    )
    session_id: uuid.UUID | None = Field(
        default=None, foreign_key="practice_session.id", ondelete="CASCADE"
    )
    # 服务端存储路径（随机文件名），不通过 API 暴露
    audio_path: str = Field(max_length=512)
    audio_mime: str = Field(default="audio/webm", max_length=100)
    duration_s: float = Field(gt=0)
    status: str = Field(default=AttemptStatus.QUEUED, max_length=16, index=True)
    # 转写与评分使用的引擎名（mock / ark / …），界面据此标注分数来源（PRD §4）
    engine: str = Field(default="mock", max_length=32)
    transcript: str | None = None
    completeness: int | None = None
    fluency: int | None = None
    accuracy: int | None = None
    overall: int | None = None
    advice: list[str] | None = Field(default=None, sa_column=Column(JSON))
    # 词汇分析（仅问答作答；PRD US-07）：命中词/覆盖比例/CEFR 参考；词表为空时为 null
    vocab: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    # rubric 四维与模拟分（仅问答 + ark 引擎；PRD US-08）：四维 0-4、mock_score 0-9、
    # upgrades 升级表达。mock 引擎或模型失败时为 null（界面显示「建议暂缺」）
    rubric: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = Field(default=None, max_length=512)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class AttemptPublic(SQLModel):
    id: uuid.UUID
    item_type: str
    item_id: uuid.UUID
    student_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    status: str
    engine: str
    duration_s: float
    transcript: str | None = None
    completeness: int | None = None
    fluency: int | None = None
    accuracy: int | None = None
    overall: int | None = None
    advice: list[str] | None = None
    vocab: dict[str, object] | None = None
    rubric: dict[str, object] | None = None
    error: str | None = None
    created_at: datetime | None = None


# 今日练习计划（GET /classes/{code}/today）：3 句复述 + 2 道该档问答
class PlanItem(SQLModel):
    type: str  # repeat | question
    id: uuid.UUID
    text: str
    audio_url: str | None = None
    suggested_seconds: int
    band: str | None = None


class PlanAttempt(SQLModel):
    item_id: uuid.UUID
    attempt_id: uuid.UUID
    status: str
    overall: int | None = None
    completeness: int | None = None
    fluency: int | None = None
    transcript: str | None = None
    advice: list[str] | None = None
    error: str | None = None


# 关卡地图（GET /classes/{code}/path）
class PathUnit(SQLModel):
    unit_id: uuid.UUID
    order_index: int
    title: str
    topic: str
    # 该生在此单元的完成轮数与最好星数
    rounds_done: int = 0
    best_stars: int | None = None
    locked: bool = False
    passage_id: uuid.UUID | None = None


class LearningPath(SQLModel):
    classroom_code: str
    unlock_all: bool
    units: list[PathUnit]


class BadgePublic(SQLModel):
    key: str
    label: str
    description: str
    awarded_at: datetime | None = None


class GamificationInfo(SQLModel):
    xp: int = 0
    streak_days: int = 0
    # 本轮星级（未结算为 null）
    session_stars: int | None = None
    badges: list[BadgePublic] = []


class TodayPlan(SQLModel):
    session_id: uuid.UUID
    classroom_code: str
    # 本轮问答档位（复述做完前等于学生当前档）
    band: str
    items: list[PlanItem]
    # 每题最新一次作答（刷新后恢复进度）
    attempts: list[PlanAttempt]
    # 同主题同档题是否已用尽（US-06 提示用）
    questions_exhausted: bool = False
    # 激励层（HUD 与结果页用；awarded_at 为今天的即「本轮获得」）
    gamification: GamificationInfo | None = None


class NextQuestion(SQLModel):
    question: ScenarioQuestionPublic | None = None
    exhausted: bool = False


# 老师名单表（GET /classes/{code}/board，PRD §8.5 2 周形态）：
# 谁交了、每题分数、音频可点开，允许先显示「评分中」
class BoardItem(SQLModel):
    item_id: uuid.UUID
    type: str
    # 最新一次作答状态；missing = 未提交
    status: str
    overall: int | None = None
    attempt_id: uuid.UUID | None = None


class BoardStudent(SQLModel):
    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    done_count: int
    total_count: int
    repeat_avg: float | None = None
    question_avg: float | None = None
    # 有非终态作答 → 前端显示「评分中」并自动刷新
    has_pending: bool
    # 当前练习档（PRD US-10：档位分布）
    current_band: str
    # 过去 7 天无任何作答且加入已超 7 天（PRD US-10：连续缺席口径的简化）
    inactive_days7: bool = False
    # 激励层（仅老师面板展示；学生端无排名）
    xp: int = 0
    streak_days: int = 0
    # 每题最新作答，与 BoardData.items 骨架按 item_id 对应
    items: list[BoardItem]


class BoardData(SQLModel):
    classroom_code: str
    class_size: int
    # 当前评分引擎（最近一次已评作答；mock=演示模式 / ark=方舟）
    engine: str = "mock"
    # 今日至少提交 1 题的人数（PRD US-10 完成率的分子；班额为分母）
    submitted_count: int
    # 尚在评分中的学生数 > 0 时前端轮询
    pending_count: int
    # 当前练习档人数分布（PRD US-10：三档人数）
    band_distribution: dict[str, int]
    students: list[BoardStudent]
    items: list[BoardItem]  # 题目骨架（顺序与各生 items 对齐）


# 学生进步轨迹（GET /classes/{code}/trail，PRD US-09）
class TrailSession(SQLModel):
    date: str  # YYYY-MM-DD（练习日，按配置时区）
    # 口语参考分：当日问答作答总评均值（与跟读完整度分开，不混线）
    speaking_avg: float | None = None
    # 跟读完整度均值（单独一条参考线）
    repeat_completeness_avg: float | None = None
    # 词汇参考档：当日最新一次问答的词表 CEFR 标签
    vocab_cefr: str | None = None
    attempt_count: int = 0


class TrailData(SQLModel):
    classroom_code: str
    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    sessions: list[TrailSession]
    # 最近一轮的档位动向（PRD US-10：维持/升/降）；不足一轮为 null
    band_change: str | None = None


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
