"""词汇模型：班级结果、逐轮汇总、错词统计（拆分自 app/models/vocabulary.py，2026-11-07）。"""

import uuid
from datetime import datetime

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


class VocabularyClassResults(SQLModel):
    """GET /classes/{code}/vocabulary/results。"""

    assignment: VocabularyAssignmentPublic | None = None
    target_count: int = 0
    completed_count: int = 0
    in_progress_count: int = 0
    not_started_count: int = 0
    students: list[VocabularyStudentResultRow] = []
    words: list[VocabularyWordStatRow] = []
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
