"""学习路径与看板模型（拆分自 app/models.py，2026-11-05）。

对外接口不变：调用方一律 `from app.models import X`，本包 __init__ 统一再导出。
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    DateTime,
)
from sqlmodel import Field, SQLModel

from app.models.base import (
    _tenant_id_field,
    get_datetime_utc,
)
from app.models.classroom import ClassroomExercisePublic
from app.models.content import (
    ExamItemSettings,
    ScenarioQuestionPublic,
    SentenceFramePublic,
)


# 徽章发放记录；定义见 app/scoring/gamification.py 的 BADGES 常量
class StudentBadge(SQLModel, table=True):
    __tablename__ = "student_badge"
    # 多租户 C1：租户归属（默认租户兜底，同 B1 锚点定式）
    tenant_id: uuid.UUID = _tenant_id_field()

    id: int | None = Field(default=None, primary_key=True)
    student_id: uuid.UUID = Field(
        foreign_key="student.id", nullable=False, ondelete="CASCADE", index=True
    )
    badge_key: str = Field(max_length=32, index=True)
    awarded_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# 今日练习计划（GET /classes/{code}/today）：3 句复述 + 2 道该档问答
class PlanItem(SQLModel):
    exam_flow: ExamItemSettings | None = None
    type: str  # passage（整篇朗读）| repeat | question | instruction（说明页）
    id: uuid.UUID
    text: str
    # 题目说明的小标题（仅 instruction 项有值）
    title: str | None = None
    translation: str | None = None
    audio_url: str | None = None
    suggested_seconds: int
    band: str | None = None
    # 听句复述的可重听次数与已听次数（仅 repeat 项；0=不限）
    replay_limit: int | None = None
    listen_used: int | None = None
    # 题目说明的「继续」确认时间（仅 instruction 项；null=未读）
    acked_at: str | None = None
    # 分级题型训练（可空=普通课堂内容）：快照与题库行同构透传
    exam_kind: str | None = None
    exam_level: str | None = None
    # IELTS Part 2 话题卡要点与准备时间
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None
    # 逐句朗读（文章拆句展开）：句子条目的合成 ID 指回真实篇目与句序
    parent_id: uuid.UUID | None = None
    sentence_index: int | None = None
    sentence_total: int | None = None
    # 可替换句型推荐（按题目实际难度与用途分类；仅考试题注入）
    frames: list[SentenceFramePublic] | None = None


class PlanAttempt(SQLModel):
    teacher_review_tags: list[str] | None = None
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
    # 词级对齐（跟读/复述）：参考文本逐词状态，结果页原文高亮用
    word_alignment: dict[str, object] | None = None
    # rubric 四维与升级表达（问答 + ark）——结果页四维条形用
    rubric: dict[str, object] | None = None
    # 提交时的参考文本。回看不能改用后来编辑过的题库正文。
    item_text: str | None = None
    error: str | None = None
    # 同题上一次 DONE 作答摘要（重录对比）：{overall, fluency, completeness,
    # created_at}；首次作答为 null
    previous: dict[str, object] | None = None

    teacher_feedback: str | None = None
    teacher_focus: bool = False
    teacher_feedback_author: str | None = None
    teacher_feedback_at: datetime | None = None


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

    automated: bool = False
    phase: str | None = None
    phase_remaining_seconds: int = 0
    phase_elapsed_seconds: int = 0
    time_limit_minutes: int
    # 服务器时间口径的剩余秒数（前端只做展示，作答以服务端校验为准）
    remaining_seconds: int
    started: bool
    ended: bool
    tab_switch_count: int = 0
    # 顺序与题目时间来自发布快照；刷新/换设备不会重新计时。
    current_item_index: int = 0
    item_remaining_seconds: int = 0
    prep_remaining_seconds: int = 0


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
    # 全班课后作业（与当前课堂发布并存；没有则为 null）
    homework_title: str | None = None
    homework_exercise_id: uuid.UUID | None = None


class NextQuestion(SQLModel):
    question: ScenarioQuestionPublic | None = None
    exhausted: bool = False


# 老师名单表（GET /classes/{code}/board，PRD §8.5 2 周形态）：
# 谁交了、每题分数、音频可点开，允许先显示「评分中」
class AssignmentItemIn(SQLModel):
    """按题指派的单条题目引用：各题型互相独立，各自成题。"""

    type: str  # passage | repeat | question | instruction
    id: uuid.UUID


class BoardItem(SQLModel):
    item_id: uuid.UUID
    type: str
    # 最新一次作答状态；missing = 未提交
    status: str
    overall: int | None = None
    attempt_id: uuid.UUID | None = None

    teacher_focus: bool = False


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
    # 模考监考信息（非考试发布为 null）：切屏次数、离屏时长与用时
    exam_tab_switches: int | None = None
    exam_tab_switch_seconds: int | None = None
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
    homework_title: str | None = None
    homework_exercise_id: uuid.UUID | None = None


class WeakWord(SQLModel):
    word: str
    student_count: int


class WeakItem(SQLModel):
    item_id: uuid.UUID
    item_type: str
    label: str
    scored_count: int
    avg_overall: float
    low_count: int


class ClassWeakSpots(SQLModel):
    """当前发布、今日会话里的共同漏词和偏低题目。"""

    word_gaps: list[WeakWord]
    low_items: list[WeakItem]


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


# 班级趋势（GET /classes/{code}/trend，教师端：全班均分与活跃度的日聚合）
class ClassTrendDay(SQLModel):
    date: str  # YYYY-MM-DD（练习日，按配置时区）
    # 当日有已完成作答的学生数（DONE 去重）
    active_students: int = 0
    # 当日情景问答作答数（DONE）
    question_attempts: int = 0
    # 当日问答总评均值（无已完成问答为 null）
    question_avg: float | None = None
    # 当日跟读完整度均值（无已完成跟读为 null）
    repeat_completeness_avg: float | None = None


class TrailData(SQLModel):
    classroom_code: str
    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    sessions: list[TrailSession]
    # 最近一轮的档位动向（PRD US-10：维持/升/降）；不足一轮为 null
    band_change: str | None = None
    # 累计开口分钟（Σ作答时长；BELP 成长页统计）
    total_minutes: int = 0
    # 累计词汇命中次数按档（老词表 A2/B1/B2 口径；仅历史作答携带，零变化保留）
    vocab_counts: dict[str, int] = {}
    # 五级词库口径的用词来源命中（现行为标准；来自 attempt.vocab.level_stats）
    level_counts: dict[str, int] = {}


# 个人弱项诊断（GET /classes/{code}/diagnostics，成长页诊断卡）
class DimensionPoint(SQLModel):
    date: str  # 练习日（按配置时区）
    fluency: float | None = None
    vocabulary: float | None = None
    grammar: float | None = None
    task: float | None = None


class StudentDiagnostics(SQLModel):
    classroom_code: str
    student_id: uuid.UUID
    # 个人高频漏词（跟读/复述，窗口 90 天）：[{word, count}]，按 count 降序
    top_missed_words: list[dict[str, object]] = []
    # 四维均值（问答 rubric，窗口 90 天；无样本时为空 dict）
    dimension_means: dict[str, float] = {}
    # 均值最小的维度（并列取 fluency/vocabulary/grammar/task 顺序）；无样本为 null
    weakest_dimension: str | None = None
    # 参与四维统计的问答作答数
    dimension_count: int = 0
    # 四维趋势（最近 14 次有完整四维的作答，按时间升序）
    dimension_trend: list[DimensionPoint] = []


# 学生历史练习列表行（GET /classes/{code}/my-sessions）：一次会话一行，
# 供「我的成长」页跳 /p/{code}/result?session=<id> 回看详细反馈。
class MySessionSummary(SQLModel):
    attempt_ids: list[uuid.UUID] = []
    is_exam: bool = False
    exam_ended: bool = False
    session_id: uuid.UUID
    session_date: date
    # daily = 课堂/发布练习轮；explore = 主题探索自由练习
    mode: str
    # 发布练习标题（assignment → ClassroomExercise.title；自主练习为 null，
    # 前端按 mode 出双语文案，不把后端中文串直接当界面文案）
    title: str | None = None
    # 完成口径与 board 一致：题单（快照）题位的最新一次作答是否 done；
    # 自主练习无固定快照分母，按该轮实际作答过的题位计
    done_count: int
    total_count: int
    # 该轮已评分作答的参考分均值（未出分/考试未终结为 null）
    overall_avg: float | None = None
