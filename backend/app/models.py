import uuid
from datetime import UTC, date, datetime

from fastapi import HTTPException
from pydantic import EmailStr, field_validator
from sqlalchemy import JSON, Column, Date, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    # 学生无邮箱：email 可空（学号登录），教师/管理员必填（API 层校验）
    email: EmailStr | None = Field(
        default=None, unique=True, index=True, max_length=255
    )
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    # 三级角色：admin（=is_superuser）/ teacher / student。
    # 不变量：role=="admin" ⇔ is_superuser，建号与迁移双写保持一致
    role: str = Field(default="teacher", max_length=16, index=True)
    # 学号（student 登录名）；教师/管理员为空。PG 唯一索引对 NULL 不去重，可空唯一安全
    username: str | None = Field(default=None, unique=True, index=True, max_length=64)
    # 批量导入的初始密码标记：首登后前端强制改密，改密接口清位
    must_change_password: bool = Field(default=False)


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
    role: str | None = Field(default=None, max_length=16)
    username: str | None = Field(default=None, max_length=64)


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
    # 中文提示（可选）：学生端题干下方展示；空则回退题型固定提示
    translation: str | None = Field(default=None, max_length=1024)
    # 标准音地址；为空时前端用 speechSynthesis 兜底（PRD §7.2）
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=45, ge=10, le=180)
    is_active: bool = True


class Passage(PassageBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=100)
    # 所属学习单元（关卡）；为空时挂全局默认（老数据兼容）
    unit_id: uuid.UUID | None = Field(
        default=None, foreign_key="unit.id", ondelete="SET NULL", index=True
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class PassagePublic(PassageBase):
    id: uuid.UUID
    slug: str
    # 所属单元：管理端要能读回指派关系（写入口同为 PassageCreate.unit_id）
    unit_id: uuid.UUID | None = None
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
    __tablename__ = "repeat_sentence"

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
    # 分级题型训练（可空=普通课堂内容，含义不变）：题型与级别分别建模
    exam_kind: str | None = Field(default=None, max_length=24)
    exam_level: str | None = Field(default=None, max_length=16)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


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


class ScenarioQuestionPublic(SQLModel):
    id: uuid.UUID
    band: str
    text: str
    audio_url: str | None = None
    suggested_seconds: int
    # 分级题型训练（可空=普通情景问法）
    exam_kind: str | None = None
    exam_level: str | None = None
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None


# 课堂码即弱密码（PRD §8.5）：无账号体系，泄露只影响一个班的成绩可见性
class Classroom(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, max_length=16)
    # 教师自定义课堂信息；课堂难度由发布时选择的内容决定，不再依赖档位。
    name: str = Field(default="未命名课堂", max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    class_size: int = Field(default=40, ge=1, le=100)
    is_active: bool = True
    # 授权教师（User.id）：教师面板/指派/名单必须由本人或管理员访问；
    # 课堂码只用于学生入班，不能凭课堂码查看全班数据
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", index=True
    )
    # 老师一键解锁全部关卡（默认顺序解锁）
    unlock_all: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    # 课堂指派（教学工具定位）：老师设定的当前单元，全班 /today 优先用它；
    # 为空时走个人路径（课后自主练习兜底）
    current_unit_id: uuid.UUID | None = Field(
        default=None, foreign_key="unit.id", ondelete="SET NULL"
    )
    # 题型指派：本轮包含的题型（专项训练）；NULL=包含（默认三种全有）
    assign_reading: bool | None = Field(default=None)
    assign_repeat: bool | None = Field(default=None)
    assign_qa: bool | None = Field(default=None)
    # 按题指派（2026-09-29 三题型独立）：[{type: passage|repeat|question, id}]
    # 非空时优先于 unit 指派；题目删除后解析时自动跳过
    assigned_items: list[dict[str, str]] | None = Field(
        default=None, sa_column=Column("assigned_items", JSON, nullable=True)
    )
    # 当前已发布练习的不可变快照；assigned_items 保留用于兼容旧数据/客户端
    current_exercise_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="classroom_exercise.id",
        ondelete="SET NULL",
        index=True,
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ClassroomPublic(SQLModel):
    id: uuid.UUID
    code: str
    name: str
    grade: str | None = None
    teaching_goal: str | None = None
    class_size: int
    is_active: bool
    unlock_all: bool = False
    owner_id: uuid.UUID | None = None
    assign_reading: bool | None = None
    assign_repeat: bool | None = None
    assign_qa: bool | None = None
    current_exercise_id: uuid.UUID | None = None
    created_at: datetime | None = None


class ClassroomExercise(SQLModel, table=True):
    """课堂一次发布的练习快照。

    题目库可以继续编辑，但已发布练习和已开始的学生会话始终使用这里保存的
    snapshot_items，避免历史作答被新内容重新解释。
    """

    __tablename__ = "classroom_exercise"
    __table_args__ = (
        UniqueConstraint(
            "classroom_id", "version_no", name="uq_classroom_exercise_version"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    version_no: int = Field(default=1, ge=1)
    title: str = Field(default="课堂练习", max_length=255)
    status: str = Field(default="published", max_length=16, index=True)
    # [{type, id, text, translation, audio_url, suggested_seconds, replay_limit, band}]
    snapshot_items: list[dict[str, object]] = Field(
        sa_column=Column("snapshot_items", JSON, nullable=False)
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    published_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    archived_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 模考模式：整场限时（分钟），学生首次打开即开始计时，到时自动交卷；
    # 考试中每题只能作答一次，切屏次数上报给教师
    is_exam: bool = Field(default=False, sa_column_kwargs={"server_default": "false"})
    time_limit_minutes: int | None = Field(default=None, ge=5, le=240)


class ClassroomExercisePublic(SQLModel):
    id: uuid.UUID
    classroom_id: uuid.UUID
    version_no: int
    title: str
    status: str
    item_count: int
    created_at: datetime | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None
    is_exam: bool = False
    time_limit_minutes: int | None = None


# 听句复述的播放计数（防刷）：一个学生一轮里对一道题听了多少次标准音
class ItemListen(SQLModel, table=True):
    __tablename__ = "item_listen"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "session_id", "item_id", name="uq_item_listen_scope"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="student.id", ondelete="CASCADE")
    session_id: uuid.UUID = Field(foreign_key="practice_session.id", ondelete="CASCADE")
    item_id: uuid.UUID = Field(index=True)
    count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


class ClassroomCreate(SQLModel):
    name: str = Field(default="未命名课堂", min_length=1, max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    class_size: int = Field(default=40, ge=1, le=100)


# 学生：与登录账号（role=student 的 User）关联；游戏化数据挂在本行
class Student(SQLModel, table=True):
    __tablename__ = "student"
    __table_args__ = (
        # suffix 为 NULL 时：同名只能一个（首个加入的不追加后缀）
        Index(
            "ix_student_classroom_display_name_no_suffix",
            "classroom_id",
            "display_name",
            unique=True,
            postgresql_where=text("suffix IS NULL"),
        ),
        # suffix 不为 NULL 时：同名+同后缀唯一
        UniqueConstraint(
            "classroom_id", "display_name", "suffix", name="uq_student_name_suffix"
        ),
        # 一个账号在一间课堂只有一份学生档案（XP/作答历史挂在档案上）
        Index(
            "ix_student_user_classroom_unique",
            "user_id",
            "classroom_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE"
    )
    # 登录账号（学生）；历史匿名数据迁移前为 NULL
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="CASCADE"
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
    # 账号制：名字可省（默认用账号姓名）
    display_name: str | None = Field(default=None, max_length=64)


class StudentPublic(SQLModel):
    id: uuid.UUID
    display_name: str
    suffix: str | None = None
    current_band: str
    classroom_id: uuid.UUID
    user_id: uuid.UUID | None = None


# 一次练习会话：一个学生一天一轮（PRD §8.4：日期、当前档、做到哪一题）
class PracticeSession(SQLModel, table=True):
    __tablename__ = "practice_session"
    __table_args__ = (
        # 已发布练习轮：按 (student, date, mode, assignment_id) 唯一。
        # assignment_id 是不可变锚（从不被 UPDATE SET NULL），内容删后 passage_id SET NULL
        # 也不会造成唯一键冲突。
        Index(
            "ix_practice_session_by_assignment",
            "student_id",
            "session_date",
            "mode",
            "assignment_id",
            unique=True,
            postgresql_where=text("assignment_id IS NOT NULL"),
        ),
        # 自主练习轮（无发布）：daily 模式下每个学生每天只开一条自主轮；
        # 删篇导致 passage_id 变 NULL 时仍落在同一条（COALESCE 保证 NULL 不冲突）。
        Index(
            "ix_practice_session_self_practice",
            "student_id",
            "session_date",
            text("COALESCE(passage_id::text, '')"),
            unique=True,
            postgresql_where=text("mode = 'daily' AND assignment_id IS NULL"),
        ),
        # 主题探索轮：(student, date, mode, passage_id) 唯一（passage 必非 NULL）
        Index(
            "ix_practice_session_explore",
            "student_id",
            "session_date",
            "mode",
            "passage_id",
            unique=True,
            postgresql_where=text("mode = 'explore' AND passage_id IS NOT NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # board/发布历史按课堂查会话；只有以 student_id 开头的部分唯一索引，
    # 不覆盖"课堂维度拉全部会话"的查询
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    # trail/结算/gamification 直查学生全部会话；部分唯一索引的 WHERE 条件
    # 不含 stars/order 等场景，需要独立的 btree
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    # 本轮开始时的档位；问答档位见 question_band
    band: str = Field(max_length=10)
    # 3 句复述做完后按规则调整出的问答档位（PRD US-05：跟读结果定问答档）
    question_band: str | None = Field(default=None, max_length=10)
    # 本轮星级（0-3，完成即 ≥1）；结算见 gamification.settle_session
    stars: int | None = Field(default=None)
    # 练习模式：daily = 课堂今日轮（教师面板统计）；explore = 主题探索自由练习
    mode: str = Field(
        default="daily", max_length=16, sa_column_kwargs={"server_default": "daily"}
    )
    # 本轮练习的篇目（关卡进度按 passage → unit 聚合）
    passage_id: uuid.UUID | None = Field(
        default=None, foreign_key="passage.id", ondelete="SET NULL"
    )
    # daily 会话固定关联发布快照；explore/旧数据为空
    assignment_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="classroom_exercise.id",
        ondelete="SET NULL",
        index=True,
    )
    session_date: date = Field(sa_type=Date)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 模考计时（仅 is_exam 的发布绑定会话）：首次打开今日计划时落开始时间；
    # 到时或交卷后落结束时间，此后拒绝继续作答
    exam_started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    exam_ended_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 换题授权（分级题型训练）：学生点「换一题」时返回的计划外题目，其
    # 完整快照（发布时刻内容，含考试字段）存入本列——提交与结果页读同一
    # 份内容，老师此后改题干/话题卡或删题均不影响学生已看到的题目
    exchanged_items: list[dict[str, object]] | None = Field(
        default=None, sa_column=Column("exchanged_items", JSON, nullable=True)
    )
    # 防切屏：前端 visibilitychange 上报的离开次数（教师面板可见）
    tab_switch_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


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


MAX_SCORING_RETRIES = 2
SCORING_STALE_TIMEOUT_S = 120  # 超过此时间的 scoring 视为僵尸


class Attempt(SQLModel, table=True):
    __tablename__ = "attempt"
    __table_args__ = (
        # 幂等键唯一：同一次录音重传不重复创建作答/扣费（并发安全）
        UniqueConstraint("idempotency_key", name="uq_attempt_idempotency_key"),
        # board 引擎探测（status=done order by created_at desc limit 1）与
        # 最新作答排序：单靠 status 索引仍要对全部 done 行排序
        Index("ix_attempt_status_created_at", "status", "created_at"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 作答对象：passage（MVP 整篇跟读）/ repeat（复述句）/ question（情景问答）
    item_type: str = Field(default=AttemptItemType.PASSAGE, max_length=16, index=True)
    item_id: uuid.UUID = Field(index=True)
    # board/trail/today/gamification 高频按学生与会话过滤，需索引
    student_id: uuid.UUID | None = Field(
        default=None, foreign_key="student.id", ondelete="CASCADE", index=True
    )
    session_id: uuid.UUID | None = Field(
        default=None, foreign_key="practice_session.id", ondelete="CASCADE", index=True
    )
    # 幂等键：同一次录音重传不重复创建作答/扣费
    idempotency_key: str | None = Field(default=None, max_length=64)
    # 提交时保存题目快照，评分不再读取可能已被编辑的题库内容
    item_snapshot: dict[str, object] | None = Field(
        default=None, sa_column=Column("item_snapshot", JSON, nullable=True)
    )
    # 服务端存储路径（随机文件名），不通过 API 暴露
    audio_path: str = Field(max_length=512)
    audio_mime: str = Field(default="audio/webm", max_length=100)
    duration_s: float = Field(gt=0)
    status: str = Field(default=AttemptStatus.QUEUED, max_length=16, index=True)
    # 评分重试次数（上限 MAX_SCORING_RETRIES）
    retry_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # worker 领取时间（用于崩溃恢复时识别僵尸 scoring）
    claimed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
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
    retry_count: int = 0
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
    type: str  # passage（整篇朗读）| repeat | question
    id: uuid.UUID
    text: str
    translation: str | None = None
    audio_url: str | None = None
    suggested_seconds: int
    band: str | None = None
    # 听句复述的可重听次数与已听次数（仅 repeat 项；0=不限）
    replay_limit: int | None = None
    listen_used: int | None = None
    # 分级题型训练（可空=普通课堂内容）：快照与题库行同构透传
    exam_kind: str | None = None
    exam_level: str | None = None
    # IELTS Part 2 话题卡要点与准备时间
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None
    # 可替换句型推荐（按题目实际难度与用途分类；仅考试题注入）
    frames: list[SentenceFramePublic] | None = None


class PlanAttempt(SQLModel):
    item_id: uuid.UUID
    attempt_id: uuid.UUID
    status: str
    overall: int | None = None
    completeness: int | None = None
    fluency: int | None = None
    transcript: str | None = None
    advice: list[str] | None = None
    # 词汇命中分析（问答）：命中词/覆盖率/CEFR——结果页命中词 tags 用
    vocab: dict[str, object] | None = None
    # rubric 四维与升级表达（问答 + ark）——结果页四维条形用
    rubric: dict[str, object] | None = None
    error: str | None = None


# 学习路径（GET /classes/{code}/path，主题探索与首页消费）
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


class AssignmentInfo(SQLModel):
    unit_id: uuid.UUID
    title: str
    # 指派前完整性检查：该单元当前的启用篇目数
    passage_count: int = 0
    # 本轮题型勾选（None=默认：复述/问答含、朗读不含）
    assign_reading: bool | None = None
    assign_repeat: bool | None = None
    assign_qa: bool | None = None


class LearningPath(SQLModel):
    classroom_code: str
    unlock_all: bool
    # 老师指派的单元（null = 个人路径模式）
    assignment: AssignmentInfo | None = None
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


class ExamStatus(SQLModel):
    """考试态信息（学生端倒计时与锁题、教师端监考）。"""

    time_limit_minutes: int
    # 服务器时间口径的剩余秒数（前端只做展示，作答以服务端校验为准）
    remaining_seconds: int
    started: bool
    ended: bool
    tab_switch_count: int = 0


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
    # 老师指派的单元标题（课堂同步练习；null = 个人路径）
    assigned_unit_title: str | None = None
    # 本轮为模考时的限时与剩余时间（非考试为 null）
    exam: ExamStatus | None = None


class NextQuestion(SQLModel):
    question: ScenarioQuestionPublic | None = None
    exhausted: bool = False


# 老师名单表（GET /classes/{code}/board，PRD §8.5 2 周形态）：
# 谁交了、每题分数、音频可点开，允许先显示「评分中」
class AssignmentItemIn(SQLModel):
    """按题指派的单条题目引用：三种题型互相独立，各自成题。"""

    type: str  # passage | repeat | question
    id: uuid.UUID


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
    # 本轮状态口径（统一统计）：not_started / in_progress / scoring / all_done / has_failures
    round_status: str = "not_started"
    # 过去 7 天无任何作答且加入已超 7 天（PRD US-10：连续缺席口径的简化）
    inactive_days7: bool = False
    # 激励层（仅老师面板展示；学生端无排名）
    xp: int = 0
    streak_days: int = 0
    # 每题最新作答，与 BoardData.items 骨架按 item_id 对应
    items: list[BoardItem]
    # 模考监考信息（非考试发布为 null）：切屏次数与用时
    exam_tab_switches: int | None = None
    exam_time_used_seconds: int | None = None
    exam_ended: bool | None = None


class BoardData(SQLModel):
    classroom_code: str
    classroom_name: str
    classroom_grade: str | None = None
    teaching_goal: str | None = None
    class_size: int
    # 当前评分引擎（最近一次已评作答；mock=演示模式 / ark=方舟）
    engine: str = "mock"
    # 老师指派的今日单元（教学工具定位）
    assignment: AssignmentInfo | None = None
    # 按题指派（三题型独立）：[{type, id}]，非空时优先于单元指派
    assigned_items: list[dict[str, str]] | None = None
    # 当前发布版本；题库内容后续编辑不应改变本次课堂看到的题目
    current_exercise: ClassroomExercisePublic | None = None
    # 今日至少提交 1 题的人数（PRD US-10 完成率的分子；班额为分母）
    submitted_count: int
    # 今日整轮全部完成的人数（"提交过一道题"不算整轮完成）
    completed_count: int
    # 尚在评分中的学生数 > 0 时前端轮询
    pending_count: int
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
    # 累计开口分钟（Σ作答时长；SpeakUp 成长页统计）
    total_minutes: int = 0
    # 累计词汇命中次数按档（SpeakUp 词汇生长条形图）
    vocab_counts: dict[str, int] = {}


# ── 词汇学习（背单词模块，2026-10-01 设计文档 P0）──────────────────
# 与口语问答词汇分析用的 WordlistEntry 完全分离：这里存的是可考的
# 教学词条（词性/释义/可接受拼写），历史作答永远按发布快照判分与展示。


class VocabularyWord(SQLModel, table=True):
    """一条可考的词义；同形异义各有独立行（不共用 lemma 唯一约束）。"""

    __tablename__ = "vocabulary_word"

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
    )

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
    # 切屏计数（沿用模考思路；P0 练习模式仅记录不启用，P1 测验接入）
    tab_switch_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


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
    mode: str = "practice"
    due_at: datetime | None = None


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
    published_at: datetime | None = None
    archived_at: datetime | None = None
    created_by: uuid.UUID | None = None


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


class VocabularyRoundSummaryRow(SQLModel):
    """学生侧轮次摘要：轮次回看入口（只读查看指定轮）。"""

    round_no: int
    status: str  # in_progress / submitted
    answered_count: int
    correct_first_count: int
    submitted_at: datetime | None = None


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


class VocabularyStudentRoundRow(SQLModel):
    """单个轮次的独立汇总（首轮=任务成绩；复习轮单独记录）。"""

    round_no: int
    status: str  # in_progress / submitted
    answered_count: int
    correct_first_count: int
    submitted_at: datetime | None = None


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


class VocabularyStudentHistoryRow(SQLModel):
    """练习历史行：一次轮次一行，kind 区分教师任务/自主练习/错词复习。

    正确率口径在行内不自算（避免画成能力成绩）：前端用
    correct_first_count / answered_count 展示首答正确率，零作答显示未作答。
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


class VocabularyStudentHistory(SQLModel):
    items: list[VocabularyStudentHistoryRow] = []


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
    # 登录角色随 token 下发，前端按角色分流（不作为权限依据，权限查库）
    role: str | None = None
    # 签发时的密码哈希前缀：与库中不一致（改密/重置过）则 token 失效
    pwd: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ── 五级词库（口语与背单词共用的统一分级数据源，2026-10-03）────────
# 级别固定顺序（越靠前越容易）；实际难度默认取最早、最易一级。
# 与口语分析用的 WordlistEntry（A2/B1/B2，整表替换）完全独立：
# 历史作答的 A2/B1/B2 词汇结果不因五级导入被重新解释。
VOCAB_LEVEL_ORDER = ("KET", "PET", "ACADEMIC", "CET4", "IELTS_TOEFL")


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
