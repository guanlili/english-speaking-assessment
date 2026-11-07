"""词汇模型：课堂词汇任务的发布与今日计划（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel


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
