"""运营与导出模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Text,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    _tenant_id_field,
    get_datetime_utc,
)
from app.models.classroom import DashboardClassroomRow

# ── 管理员平台大盘（业务数据闭环，2026-10 设计稿）────────────────
# 口径与教师端一致：练习日按 PRACTICE_TZ 切，均分只算 DONE 作答
# （模考作答评分完成即 DONE，同样计入；与班级趋势同口径）。


class DashboardRangeCards(SQLModel):
    """速览卡一组：同一口径下「今日」与「所选区间」各一份。"""

    attempts: int
    active_students: int
    active_classrooms: int
    scored_done: int
    scored_failed: int
    exam_sessions: int
    runtime_issues: int


class DashboardOverview(SQLModel):
    days: int
    range_start: str  # 所选区间首日（含今日），ISO 日期
    today: DashboardRangeCards
    range: DashboardRangeCards


class DashboardDailyPoint(SQLModel):
    """大盘日点：活跃/作答量按全部提交计（含评分失败），均分只算 DONE。"""

    date: str
    active_students: int
    active_classrooms: int
    attempts: int
    attempts_passage: int
    attempts_repeat: int
    attempts_question: int
    scored_failed: int
    question_avg: float | None
    repeat_completeness_avg: float | None


class DashboardUsage(SQLModel):
    points: list[DashboardDailyPoint]
    item_distribution: dict[str, int]
    classrooms: list[DashboardClassroomRow]
    silent_classrooms: list[DashboardClassroomRow]


class DashboardContent(SQLModel):
    """内容与账号资产计数（全平台存量，不随时间范围变化）。"""

    units: int
    passages: int
    repeat_sentences: int
    scenario_questions: int
    instructions: int
    vocab_books: int
    vocab_words: int
    vocab_level_entries: int
    users_admin: int
    users_teacher: int
    student_accounts: int
    students_must_change_password: int
    student_profiles: int
    classrooms_total: int
    classrooms_active: int
    publishes: int
    publishes_exam: int


class AdminMetricsDaily(SQLModel, table=True):
    """大盘日快照：业务量精确回算自明细表；运行时峰值来自进程内采样
    （重启丢当日峰值前的样本，字段为 null 表示当日无采样）。"""

    __tablename__ = "admin_metrics_daily"

    day: date = Field(sa_type=Date, primary_key=True)
    attempts: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    attempts_done: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    attempts_failed: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    active_students: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    sessions: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # 当日作答音频总秒数（ASR 用量计费基数；P2 费用区复用）
    asr_seconds: float = Field(default=0.0, sa_column_kwargs={"server_default": "0"})
    # 进程计数器的当日增量（重启容忍：基线重置后增量从 0 起算）
    llm_calls_by_kind: dict[str, int] | None = Field(default=None, sa_type=JSON)
    # LLM 真实 token 当日累计（Ark usage 记账）；null=当日未记账，
    # 费用区该月回退「调用次数 × 估算 token」
    llm_tokens_in: int | None = Field(default=None)
    llm_tokens_out: int | None = Field(default=None)
    # 当日观测到的孤儿音频数（无引用的顶层文件；每日清理循环回收）
    audio_orphans: int | None = Field(default=None)
    provider_failures: dict[str, int] | None = Field(default=None, sa_type=JSON)
    # 当日观测峰值（60s 采样；无样本为 null）
    queue_max_age_s: float | None = Field(default=None)
    pool_max_checked_out: int | None = Field(default=None)
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class DashboardMetricsDay(SQLModel):
    """大盘性能区历史行（API 响应用，非表）。"""

    date: str
    attempts: int
    attempts_done: int
    attempts_failed: int
    active_students: int
    sessions: int
    asr_seconds: float
    llm_calls_by_kind: dict[str, int] | None = None
    provider_failures: dict[str, int] | None = None
    queue_max_age_s: float | None = None
    pool_max_checked_out: int | None = None
    audio_orphans: int | None = None


class DashboardPerformance(SQLModel):
    """大盘性能区：实时快照（与 /admin/metrics 同口径）+ 日快照历史。"""

    realtime: dict[str, object]
    history: list[DashboardMetricsDay]
    runtime_issues_today: int


class AdminCostReconcile(SQLModel, table=True):
    """费用对账：管理员手工录入的当月实际账单金额（估算 vs 实际）。"""

    __tablename__ = "admin_cost_reconcile"

    # 月份 'YYYY-MM'（主键；展示层补 '-01' 成日期处理）
    month: str = Field(max_length=7, primary_key=True)
    amount_cny: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class DashboardCostMonth(SQLModel):
    """费用月度行：分项估算 + 实际对账（未录为 null）。"""

    month: str
    asr_seconds: float
    llm_calls: int
    # tokens = LLM 计费基数来自真实 usage；estimated = 回退调用量估算
    llm_basis: str
    llm_tokens_in: int | None = None
    llm_tokens_out: int | None = None
    asr_cny: float
    llm_cny: float
    server_cny: float
    total_cny: float
    attempts: int
    # 实际账单（对账录入；未录 null）
    actual_cny: float | None = None
    deviation_pct: float | None = None


class DashboardCost(SQLModel):
    months: list[DashboardCostMonth]
    prices: dict[str, float]
    note: str


class AdminCostReconcileIn(SQLModel):
    # 月份格式 YYYY-MM 在接口层校验（SQLModel Field 不支持 pattern）
    month: str = Field(max_length=7)
    amount_cny: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)


class ChangelogEntry(SQLModel, table=True):
    """平台更新日志：管理员发布，教师与管理员可见（学生端不开放）。

    date 是面向读者的发布日期（手动指定，允许补录），排序按
    (date, created_at) 倒序；kind 为空表示无类型标签。
    """

    __tablename__ = "changelog_entry"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    day: date = Field(sa_type=Date, index=True)
    kind: str | None = Field(default=None, max_length=16)
    title_zh: str = Field(min_length=1, max_length=200)
    title_en: str = Field(min_length=1, max_length=200)
    body_zh: str | None = Field(default=None, sa_type=Text)
    body_en: str | None = Field(default=None, sa_type=Text)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ChangelogCreate(SQLModel):
    day: date
    kind: str | None = Field(default=None, max_length=16)
    title_zh: str = Field(min_length=1, max_length=200)
    title_en: str = Field(min_length=1, max_length=200)
    body_zh: str | None = Field(default=None, max_length=5000)
    body_en: str | None = Field(default=None, max_length=5000)


class ChangelogUpdate(SQLModel):
    day: date | None = None
    kind: str | None = None
    title_zh: str | None = Field(default=None, min_length=1, max_length=200)
    title_en: str | None = Field(default=None, min_length=1, max_length=200)
    body_zh: str | None = Field(default=None, max_length=5000)
    body_en: str | None = Field(default=None, max_length=5000)


class ChangelogPublic(SQLModel):
    id: uuid.UUID
    day: date
    kind: str | None
    title_zh: str
    title_en: str
    body_zh: str | None
    body_en: str | None
    created_at: datetime | None
    updated_at: datetime | None


# 口语原音频 ZIP 导出。队列在数据库（ExportJob），工人是独立线程池，
# 不与评分 SCORING_WORKERS 共用。成品在 EXPORT_STORAGE_DIR，到期删除。
class ExportScope:
    SELF = "self"
    CLASSROOM = "classroom"


class ExportKind:
    """导出成品类型。旧行与未传 kind 的录音任务都是 audio_zip。"""

    AUDIO_ZIP = "audio_zip"
    STUDENT_REPORT_PDF = "student_report_pdf"
    CLASS_REPORT_PDF = "class_report_pdf"


class ExportJobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class ExportJob(SQLModel, table=True):
    __tablename__ = "export_job"
    __table_args__ = (
        Index(
            "ix_export_job_requester_created",
            "requester_user_id",
            "created_at",
        ),
        Index("ix_export_job_status_expires", "status", "expires_at"),
    )
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    requester_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # self = 学生（或任何账号）导出自己的作答；classroom = 授权教师导出一班
    scope: str = Field(max_length=16, index=True)
    # audio_zip（默认，含本列加入前的旧行）| student_report_pdf
    kind: str = Field(
        default=ExportKind.AUDIO_ZIP,
        max_length=32,
        index=True,
        sa_column_kwargs={"server_default": ExportKind.AUDIO_ZIP},
    )
    filter_json: dict[str, object] = Field(
        sa_column=Column("filter_json", JSON, nullable=False)
    )
    status: str = Field(default=ExportJobStatus.QUEUED, max_length=16, index=True)
    progress_done: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    progress_total: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # 稳定错误码（export_empty / export_all_missing / export_too_large）
    # 或不可预期失败的短消息。空表示没有错误。
    error: str | None = Field(default=None, max_length=512)
    # 仅文件名，相对 EXPORT_STORAGE_DIR，防止把绝对路径透出 API
    artifact_relpath: str | None = Field(default=None, max_length=255)
    byte_size: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    included_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    missing_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    download_name: str | None = Field(default=None, max_length=255)
    confirm_contains_student_audio: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    downloaded_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class ExportAudit(SQLModel, table=True):
    """导出审计：谁、何时、范围、任务、结果。教师课堂导出必须留痕。"""

    __tablename__ = "export_audit"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID | None = Field(
        default=None, foreign_key="export_job.id", ondelete="CASCADE", index=True
    )
    actor_user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # create / start / success / fail / download / retry / expire / reject
    action: str = Field(max_length=16, index=True)
    scope: str | None = Field(default=None, max_length=16)
    detail: dict[str, object] | None = Field(
        default=None, sa_column=Column("detail", JSON, nullable=True)
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
