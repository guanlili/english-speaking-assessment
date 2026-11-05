"""课堂与作答模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import time
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
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


# 课堂码即弱密码（PRD §8.5）：无账号体系，泄露只影响一个班的成绩可见性
class Classroom(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, max_length=16)
    # 租户归属随 owner 落库（B1 列级默认兜底，收紧期改为显式注入+复核）
    tenant_id: uuid.UUID = _tenant_id_field()
    # 教师自定义课堂信息；课堂难度由发布时选择的内容决定，不再依赖档位。
    name: str = Field(default="未命名课堂", max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    class_size: int = Field(default=60, ge=1, le=100)
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
    # 课后作业：与课上当前发布分开，再发布课堂练习不会顶掉它。
    homework_exercise_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="classroom_exercise.id",
        ondelete="SET NULL",
        index=True,
    )
    # 学生个人学情 PDF 是否写入班级位置。默认开；样本不足 5 人时仍不显示数字。
    show_report_percentile: bool = Field(
        default=True, sa_column_kwargs={"server_default": "true"}
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
    show_report_percentile: bool = True
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
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", nullable=False, ondelete="CASCADE", index=True
    )
    version_no: int = Field(default=1, ge=1)
    title: str = Field(default="课堂练习", max_length=255)
    status: str = Field(default="published", max_length=16, index=True)
    # 指定学生补练：独立快照和固定名单，不改变课堂 current_exercise_id。
    target_students: list[dict[str, str]] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    source_exercise_id: uuid.UUID | None = Field(
        default=None, foreign_key="classroom_exercise.id", ondelete="SET NULL"
    )
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


class ComposerDraft(SQLModel, table=True):
    """每位教师、每间课堂各一份私有组卷草稿。"""

    __tablename__ = "composer_draft"
    __table_args__ = (
        UniqueConstraint("classroom_id", "owner_id", name="uq_composer_draft_owner"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", ondelete="CASCADE", index=True
    )
    owner_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    # 初始版本不从 1 重用，避免发布删除后新建草稿接受旧页面的同号版本。
    revision: int = Field(
        default_factory=lambda: time.time_ns() // 1000,
        sa_column=Column(BigInteger, nullable=False),
    )
    state: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


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
    # C2：作用域加租户前缀（跨校学生/会话 UUID 本不重叠，加列是 RLS 收口
    # 前 UPSERT 语义与租户核验的正统化）；class_runtime 的原生 UPSERT
    # 按本约束名引用，两处必须同步
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "student_id",
            "session_id",
            "item_id",
            name="uq_item_listen_scope",
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    student_id: uuid.UUID = Field(foreign_key="student.id", ondelete="CASCADE")
    session_id: uuid.UUID = Field(foreign_key="practice_session.id", ondelete="CASCADE")
    item_id: uuid.UUID = Field(index=True)
    count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


class ClassroomCreate(SQLModel):
    name: str = Field(default="未命名课堂", min_length=1, max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    class_size: int = Field(default=60, ge=1, le=100)


# 学生：与登录账号（role=student 的 User）关联；游戏化数据挂在本行
class Student(SQLModel, table=True):
    classroom_activity: dict[str, object] | None = Field(default=None, sa_type=JSON)
    # 租户随课堂推导（B1 列级默认兜底；回填/收紧期校验与课堂一致）
    tenant_id: uuid.UUID = _tenant_id_field()

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
        Index(
            "ix_practice_session_followup",
            "student_id",
            "assignment_id",
            unique=True,
            postgresql_where=text("mode = 'followup' AND assignment_id IS NOT NULL"),
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
        # 大盘与日快照按练习日统计（session_date == day / GROUP BY）：
        # 上述唯一索引全部 student_id 打头，纯日期条件不可用
        Index("ix_practice_session_session_date", "session_date"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    exam_flow_state: dict[str, dict[str, str]] | None = Field(
        default=None, sa_type=JSON
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
    # 模考计时（仅 is_exam 的发布绑定会话）：学生在开考确认页点「开始考试」
    # 时落开始时间（防误触打开即烧时间）；到时或交卷后落结束时间，此后拒绝继续作答
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
    runtime_issue: str | None = Field(default=None, max_length=32)
    runtime_issue_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # 防切屏：前端 visibilitychange 上报的离开次数（教师面板可见）
    tab_switch_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # 防切屏：切回时上报的累计离屏秒数（教师面板可见；单次封顶 1 小时）
    tab_switch_seconds: int = Field(default=0, sa_column_kwargs={"server_default": "0"})


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
    # 题目说明：纯文字引导页，无作答（学生点「继续」后进入下一题），
    # 永远不进 POST /attempts 的 item_type 白名单
    INSTRUCTION = "instruction"


MAX_SCORING_RETRIES = 2

SCORING_STALE_TIMEOUT_S = 120  # 超过此时间的 scoring 视为僵尸

# QUEUED 超过此时间无人领取视为孤儿（线程池 future 丢失等）；
# 取值需大于队列打满时的最长排队时间（200 条 / 8 worker × ~60s ≈ 25min 的量级），
# 重投本身幂等，宁可晚投不可错杀
QUEUED_STALE_TIMEOUT_S = 30 * 60


class Attempt(SQLModel, table=True):
    __tablename__ = "attempt"
    __table_args__ = (
        # 幂等键唯一：同一次录音重传不重复创建作答/扣费（并发安全）
        UniqueConstraint("idempotency_key", name="uq_attempt_idempotency_key"),
        # board 引擎探测（status=done order by created_at desc limit 1）与
        # 最新作答排序：单靠 status 索引仍要对全部 done 行排序
        Index("ix_attempt_status_created_at", "status", "created_at"),
        # 大盘区间聚合与日快照回算按 created_at 时间裁剪；status 打头的
        # 复合索引对纯时间条件不可用
        Index("ix_attempt_created_at", "created_at"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

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
    # 保留期清理的完成标记（批次06）：文件被删除或结算（缺失/越界/content）
    # 的时刻；NULL = 未处理。有标记后清理批次才能推进——此前只删文件不记
    # 状态，候选超过单轮上限后会永远重复选中同一批已删记录
    audio_purged_at: datetime | None = Field(
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
    # 词级对齐（仅跟读/复述作答）：参考文本逐词状态（correct/missing/error
    # + heard）+ 多读词。结果页原文高亮与个人漏词聚合共用，不参与评分。
    word_alignment: dict[str, object] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    # rubric 四维与模拟分（仅问答 + ark 引擎；PRD US-08）：四维 0-4、mock_score 0-9、
    # upgrades 升级表达。mock 引擎或模型失败时为 null（界面显示「建议暂缺」）
    rubric: dict[str, object] | None = Field(default=None, sa_column=Column(JSON))
    teacher_review_tags: list[str] | None = Field(default=None, sa_type=JSON)
    teacher_feedback: str | None = Field(default=None, max_length=4000)
    teacher_focus: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    teacher_feedback_author: str | None = Field(default=None, max_length=255)
    teacher_feedback_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    teacher_feedback_revision: int = Field(
        default=0, sa_column_kwargs={"server_default": "0"}
    )
    error: str | None = Field(default=None, max_length=512)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class AttemptPublic(SQLModel):
    teacher_review_tags: list[str] | None = None
    id: uuid.UUID
    item_type: str
    item_id: uuid.UUID
    student_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    status: str
    engine: str
    duration_s: float
    retry_count: int = 0
    # 题干投影（提交时快照）：title 仅篇目/说明有；text 即题目文本/引导文。
    # 教师逐题反馈弹窗与学生历史回看不依赖活题库即可展示题干。
    item_title: str | None = None
    item_text: str | None = None
    transcript: str | None = None
    completeness: int | None = None
    fluency: int | None = None
    accuracy: int | None = None
    overall: int | None = None
    advice: list[str] | None = None
    vocab: dict[str, object] | None = None
    word_alignment: dict[str, object] | None = None
    rubric: dict[str, object] | None = None
    teacher_feedback: str | None = None
    teacher_focus: bool = False
    teacher_feedback_author: str | None = None
    teacher_feedback_at: datetime | None = None
    teacher_feedback_revision: int = 0
    error: str | None = None
    created_at: datetime | None = None


class ClassroomReview(SQLModel, table=True):
    """Teacher-only discussion notes and an explicitly published class summary."""

    __tablename__ = "classroom_review"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    exercise_id: uuid.UUID = Field(
        primary_key=True, foreign_key="classroom_exercise.id", ondelete="CASCADE"
    )
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", ondelete="CASCADE", index=True
    )
    notes: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    summary: str = Field(default="", max_length=4000)
    published_summary: str | None = Field(default=None, max_length=4000)
    published_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revision: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class FollowupBatch(SQLModel, table=True):
    """Receipt for one atomic, idempotent individualized-practice assignment."""

    __tablename__ = "followup_batch"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", ondelete="CASCADE", index=True
    )
    created_by: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE")
    payload_hash: str = Field(max_length=64)
    task_ids: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ClassroomMessage(SQLModel, table=True):
    """A student's help request or a teacher's individually acknowledged reminder."""

    __tablename__ = "classroom_message"
    __table_args__ = (
        UniqueConstraint(
            "classroom_id",
            "student_id",
            "kind",
            "request_id",
            name="uq_classroom_message_request",
        ),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    classroom_id: uuid.UUID = Field(
        foreign_key="classroom.id", ondelete="CASCADE", index=True
    )
    student_id: uuid.UUID = Field(
        foreign_key="student.id", ondelete="CASCADE", index=True
    )
    created_by: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    request_id: uuid.UUID
    kind: str = Field(max_length=16, index=True)
    category: str | None = Field(default=None, max_length=32)
    text: str = Field(default="", max_length=500)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    read_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reply_text: str | None = Field(default=None, max_length=500)
    replied_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reply_revision: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    due_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reminder_of: uuid.UUID | None = Field(
        default=None,
        foreign_key="classroom_message.id",
        ondelete="SET NULL",
        index=True,
    )
    resolution: str | None = Field(default=None, max_length=16)
    resolved_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class DashboardClassroomRow(SQLModel):
    classroom_id: uuid.UUID
    name: str
    code: str
    grade: str | None
    owner_name: str | None
    students: int
    attempts: int  # 所选区间内提交数
    avg_score: float | None  # 区间内 DONE 作答 overall 均分
    attempts_all: int  # 历史累计（从未使用=0）
    last_active: datetime | None  # 历史最近一次作答（UTC）
    silent_days: int | None  # 距最近作答天数；从未使用为 None
