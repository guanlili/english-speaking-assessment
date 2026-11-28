"""学生词汇坐标：0%–100% 贯通进度与台阶（#616）。

口径（对外文案必须一致遵守）：

- 坐标是**学习进度**，不是雅思/托福分数，不是能力认证，也不预测考试分数。
- 分子 = 本人已「掌握」的词条数，分母 = 本人当前可练基准词表词数
  （`student_practiceable_word_ids`：active 公共库 + 本班库内 approved 的
  active 词条）。两者都取当前口径，分母变化后百分比可整体复算——这一点
  写进接口返回值（basis_word_count），老师能自己核对。
- 「掌握」只看两类证据，不读 XP / 农场 / PK / 任务完成率：
  1. 独立首答（attempt_no=1）答对——任意轮次（任务 / 自主 / 复习），
     测验答卷沿用错词本同一条答案可见规则（公布前不计数，避免提前泄露
     对错的自我确认）；
  2. FSRS 状态进入 `review`（认读/拼写任一能力维度建立长期记忆）。
- 台阶数量可变（默认 12，接口可传 steps），台阶是等宽的百分比区间，
  左闭右开、100% 归最后一阶；不把 12–18 写死，也不按台阶宣称等级。
- 一条首答都没有 → `measured=False`，百分比下发 None（「未测」），
  不折算成 0%，避免把没测过的学生标成零基础。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app.models import (
    COORDINATE_STEP_COUNT_DEFAULT,
    COORDINATE_STEP_COUNT_MAX,
    COORDINATE_STEP_COUNT_MIN,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyReviewState,
    VocabularySession,
)
from app.models.vocabulary.review import REVIEW_STATE_REVIEW
from app.services import vocabulary as vocab_service

# 台阶数量的可配范围与默认值定义在模型层（接口与前端共用同一份常量）


@dataclass(frozen=True)
class CoordinateSnapshot:
    """一次坐标计算的中间结果（纯数据，便于单测与复算）。"""

    measured: bool
    answered_first_count: int
    mastered_first_try_count: int
    mastered_fsrs_count: int
    mastered_word_count: int
    basis_word_count: int
    percent: int | None
    steps_total: int
    step_index: int | None
    step_start_percent: int | None
    step_end_percent: int | None
    words_to_next_step: int | None
    words_to_goal: int | None


def compute_coordinate(
    *,
    answered_first_count: int,
    mastered_first_try_count: int,
    mastered_fsrs_count: int,
    basis_word_count: int,
    steps: int = COORDINATE_STEP_COUNT_DEFAULT,
) -> CoordinateSnapshot:
    """纯函数：把计数换算成百分比与台阶（不含任何数据库读取）。

    边界口径：
    - basis=0（还没有可练词库）→ 未测，百分比 None；
    - 首答数为 0 → 未测，百分比 None（不折算 0%）；
    - 两个掌握来源取并集时由调用方保证已去重（同一词不重复计）；
    - percent ∈ [0,100]，向下取整用「四舍五入到整数」，100% 只在
      掌握数达到基准词数时出现。
    """
    steps = max(COORDINATE_STEP_COUNT_MIN, min(COORDINATE_STEP_COUNT_MAX, steps))
    basis = max(0, basis_word_count)
    mastered = max(0, min(basis, mastered_first_try_count + mastered_fsrs_count))
    measured = basis > 0 and answered_first_count > 0

    if basis == 0:
        return CoordinateSnapshot(
            measured=False,
            answered_first_count=answered_first_count,
            mastered_first_try_count=mastered_first_try_count,
            mastered_fsrs_count=mastered_fsrs_count,
            mastered_word_count=mastered,
            basis_word_count=0,
            percent=None,
            steps_total=steps,
            step_index=None,
            step_start_percent=None,
            step_end_percent=None,
            words_to_next_step=None,
            words_to_goal=None,
        )

    percent = min(100, int(100 * mastered / basis + 0.5)) if measured else None
    if percent is None:
        return CoordinateSnapshot(
            measured=False,
            answered_first_count=answered_first_count,
            mastered_first_try_count=mastered_first_try_count,
            mastered_fsrs_count=mastered_fsrs_count,
            mastered_word_count=mastered,
            basis_word_count=basis,
            percent=None,
            steps_total=steps,
            step_index=None,
            step_start_percent=None,
            step_end_percent=None,
            words_to_next_step=None,
            words_to_goal=basis - mastered,
        )

    width = 100 / steps
    # 左闭右开：percent 落在 [k*width, (k+1)*width) 即第 k+1 阶；100% 归最后一阶
    step_index = min(steps, int(percent / width) + 1)
    step_start = int((step_index - 1) * width)
    step_end = 100 if step_index == steps else int(step_index * width)
    words_to_step_end = ceil_count(basis, step_end)
    words_to_next = max(0, words_to_step_end - mastered) if step_index < steps else 0
    return CoordinateSnapshot(
        measured=True,
        answered_first_count=answered_first_count,
        mastered_first_try_count=mastered_first_try_count,
        mastered_fsrs_count=mastered_fsrs_count,
        mastered_word_count=mastered,
        basis_word_count=basis,
        percent=percent,
        steps_total=steps,
        step_index=step_index,
        step_start_percent=step_start,
        step_end_percent=step_end,
        words_to_next_step=words_to_next,
        words_to_goal=max(0, basis - mastered),
    )


def ceil_count(basis: int, percent: int) -> int:
    """百分比阈值对应的词数（向上取整，保证「达到该阶终点」是可算的）。"""
    if basis <= 0:
        return 0
    return -((-basis * percent) // 100)


def _first_answer_rows(
    session: Session, student_id: uuid.UUID
) -> list[tuple[uuid.UUID, bool]]:
    """本人全部独立首答（attempt_no=1）的（词条, 对错），答案可见规则同错词本。"""
    rows = session.exec(
        select(VocabularyAnswer.word_id, VocabularyAnswer.is_correct)
        .join(
            VocabularySession,
            VocabularySession.id == VocabularyAnswer.session_id,  # ty: ignore[invalid-argument-type]
        )
        .outerjoin(
            VocabularyAssignment,
            VocabularyAssignment.id == VocabularySession.assignment_id,  # ty: ignore[invalid-argument-type]
        )
        .where(
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            VocabularyAnswer.attempt_no == 1,
            (col(VocabularySession.assignment_id).is_(None))  # type: ignore[union-attr]
            | (col(VocabularyAssignment.mode) != "quiz")  # type: ignore[operator]
            | col(VocabularyAssignment.answers_published_at).is_not(None),  # type: ignore[union-attr]
        )
    ).all()
    return [(word_id, bool(is_correct)) for word_id, is_correct in rows]


def _fsrs_review_word_ids(session: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """FSRS 已建立长期记忆（state=review）的词条，按账号跨班汇总。"""
    rows = session.exec(
        select(VocabularyReviewState.word_id).where(
            VocabularyReviewState.user_id == user_id,  # type: ignore[arg-type]
            VocabularyReviewState.state == REVIEW_STATE_REVIEW,
        )
    ).all()
    return set(rows)


def coordinate_for_student(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    user_id: uuid.UUID,
    steps: int = COORDINATE_STEP_COUNT_DEFAULT,
) -> CoordinateSnapshot:
    """按当前基准词表口径计算学生坐标（纯读，不写任何状态）。"""
    basis_ids = vocab_service.student_practiceable_word_ids(session, classroom_id)
    rows = _first_answer_rows(session, student_id)
    first_correct: set[uuid.UUID] = {w for w, ok in rows if ok}
    fsrs_ids = _fsrs_review_word_ids(session, user_id)

    answered = {w for w, _ in rows}
    # 分子按当前基准词表口径取交集：词条被归档后不再计入，分母同步变化
    first_hit = first_correct & basis_ids
    fsrs_hit = fsrs_ids & basis_ids
    return compute_coordinate(
        answered_first_count=len(answered),
        mastered_first_try_count=len(first_hit),
        mastered_fsrs_count=len(fsrs_hit - first_hit),
        basis_word_count=len(basis_ids),
        steps=steps,
    )
