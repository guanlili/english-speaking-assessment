"""词汇模型：班级结果、逐轮汇总、错词统计（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import date, datetime

from sqlmodel import SQLModel

from app.models.vocabulary.assignments import (
    VocabularyAssignmentPublic,
)


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


class VocabularyPromptTypeStat(SQLModel):
    """按出题方式的首答正确率（教师看清哪类题型在掉分，不合成总分）。"""

    prompt_type: str
    answered_count: int = 0
    correct_first_count: int = 0


class VocabularyClassResults(SQLModel):
    """GET /classes/{code}/vocabulary/results。"""

    assignment: VocabularyAssignmentPublic | None = None
    target_count: int = 0
    completed_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    students: list[VocabularyStudentResultRow] = []
    words: list[VocabularyWordStatRow] = []
    # 按出题方式拆分（首答口径）；旧任务只有 meaning/audio 时也照此输出
    prompt_type_stats: list[VocabularyPromptTypeStat] = []
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

    mastered 是「移出」判定：最近一次首答判错后连续两次独立首答答对
    即掌握，移出生词本待攻克区（mastered_at 为达成时间）；之后再首答
    判错会自动回到待攻克区，掌握状态作废。它同样不是考试分数。
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
    # 是否已判定掌握（自动移出生词本待攻克区）
    mastered: bool = False
    mastered_at: datetime | None = None


class VocabularyWrongWords(SQLModel):
    """错词本分区响应：待攻克（items）+ 已掌握（mastered_items，自动移出）。

    两区共用同一次聚合，计数与首页 wrong_word_count 同口径（都只算
    待攻克）。已掌握区只做展示与凭据回看，不再进复习选题。
    """

    classroom_code: str
    items: list[VocabularyWrongWordItem] = []
    mastered_items: list[VocabularyWrongWordItem] = []
    active_count: int = 0
    mastered_count: int = 0


# ── 班级掌握度（mastery）─────────────────────────────────────────────
# 口径提醒（前后端文案一致遵守）：掌握度 = 窗口内教师任务轮首答正确率分段
# + FSRS 状态分布 + 到期未复习条目数；它不是考试分数、不是能力等级。
# ``wrong_count`` 仍只表示历史错误次数，不参与掌握度判定。
MASTERY_BAND_LOW = "low"
MASTERY_BAND_MID = "mid"
MASTERY_BAND_HIGH = "high"
MASTERY_BAND_NO_DATA = "no_data"

# 可选时间窗（天）；缺省 30 天
MASTERY_WINDOW_DAYS = (7, 30, 90)
MASTERY_DEFAULT_WINDOW_DAYS = 30


class VocabularyMasteryWordRow(SQLModel):
    """逐词掌握度行：首答分段 + 该词在本班的 FSRS 状态条目分布。"""

    word_id: uuid.UUID
    headword: str
    meaning_zh: str
    answered_count: int
    correct_first_count: int
    # 首答正确率 0..100；无首答为 None（界面显示 –，不画成 0%）
    accuracy_rate: int | None = None
    # low / mid / high / no_data
    band: str
    # 本班学生在该词上的 FSRS 状态条目数（按 user × word × capability 计）
    fsrs_new: int = 0
    fsrs_learning: int = 0
    fsrs_review: int = 0
    # 已到期（含逾期）状态条目数；是条目数，不是去重词数
    due_count: int = 0


class VocabularyMasteryReport(SQLModel):
    """GET /classes/{code}/vocabulary/mastery 的班级掌握度载荷。"""

    classroom_code: str
    generated_at: datetime
    window_days: int
    # all_tasks = 本班全部教师任务；assignment = 指定任务
    scope: str
    assignment_id: uuid.UUID | None = None
    answered_count: int = 0
    correct_first_count: int = 0
    accuracy_rate: int | None = None
    low_count: int = 0
    mid_count: int = 0
    high_count: int = 0
    no_data_count: int = 0
    # FSRS 状态条目分布（本班在册学生）
    fsrs_new: int = 0
    fsrs_learning: int = 0
    fsrs_review: int = 0
    # 到期未复习状态条目数（条目数，不是词数）
    due_count: int = 0
    words: list[VocabularyMasteryWordRow] = []


class VocabularyRecommendationFocus(SQLModel):
    """推荐复习的错词（只列最近真实错过的词，不含预测）。"""

    word_id: uuid.UUID
    headword: str
    meaning_zh: str
    wrong_count: int
    practiceable: bool = True


class VocabularyRecommendation(SQLModel):
    """基础学习推荐：规则算出，可解释，不是能力认证。

    basis 是稳定代码（no_history / low_accuracy / mid_accuracy /
    high_accuracy / wrong_focus / no_practiceable_book），前端做双语映射，
    后端不拼中文句子（与项目双语口径一致）。
    """

    classroom_code: str
    generated_at: datetime
    answered_total: int = 0
    correct_first_total: int = 0
    accuracy: float | None = None
    basis: list[str] = []
    suggested_word_count: int = 10
    suggested_prompt_types: list[str] = []
    focus_words: list[VocabularyRecommendationFocus] = []
    # 固定文案：规则推荐，不作为能力等级或考试结论
    note_code: str = "rule_based_not_certification"


# ── 跨任务 / 时间趋势（#517 C）─────────────────────────────────────


class VocabularyTrendPeriod(SQLModel):
    """单个统计周期（周/月）的聚合结果。

    区间为**闭区间**：``period_start`` 00:00:00 至 ``period_end`` 23:59:59
    （Asia/Shanghai）。``completion_rate`` / ``first_accuracy`` 在无目标 /
    无首答时返回 ``null``，不折算 0%。

    ``due_unreviewed`` 按**当前** ``VocabularyReviewState`` 回算（词 × 能力
    条目数，非去重词数）；历史周期的到期状态不做历史还原，仅作教学参考。
    """

    period_start: date
    period_end: date
    assigned_targets: int = 0
    completed_targets: int = 0
    # 0–100 取整；assigned_targets=0 → null
    completion_rate: int | None = None
    first_answered: int = 0
    first_correct: int = 0
    # 0–100 取整；无首答 → null
    first_accuracy: int | None = None
    # 掌握度分段（与现有 mastery 同阈值：<60 / 60–85 / >85 / 无首答）
    low_count: int = 0
    mid_count: int = 0
    high_count: int = 0
    no_data_count: int = 0
    # 当前状态回算的到期未复习条目数（历史周期仅教学参考）
    due_unreviewed: int = 0


class VocabularyTrendReport(SQLModel):
    """GET /classes/{code}/vocabulary/trend。

    ``teaching_reference`` 固定为 ``true``：趋势为教学参考，不是考试分数或
    能力认证。
    """

    classroom_code: str
    granularity: str  # week | month
    periods: int
    anchor: date | None = None
    generated_at: datetime
    book_id: uuid.UUID | None = None
    prompt_type: str | None = None
    teaching_reference: bool = True
    items: list[VocabularyTrendPeriod] = []
