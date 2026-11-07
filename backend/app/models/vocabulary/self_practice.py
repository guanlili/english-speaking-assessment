"""词汇模型：学生自主练习与学习报告（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.vocabulary.assignments import (
    VocabularyTodayItem,
)

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
