"""基础学习推荐：规则算，可解释，不冒充能力认证（issue #517 第一批）。

口径：
- 只读学生自己的真实首答（练习任务与自主轮；测验在答案公布前不计），
  重试不冲高正确率。
- 推荐词数与题型来自固定阈值规则，不是模型预测，不输出 CEFR/等级结论。
- 错词来自错词本里仍可练的词条，按累计错误次数排序；不预测「即将遗忘」。
"""

import uuid
from datetime import UTC, datetime

from sqlmodel import Session, col, select

from app.models import (
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyRecommendation,
    VocabularyRecommendationFocus,
    VocabularySession,
)
from app.services import vocabulary as vocab_service

LOW_ACCURACY = 0.6
HIGH_ACCURACY = 0.85
FOCUS_LIMIT = 5


def build_recommendation(
    session: Session, classroom_id: uuid.UUID, student_id: uuid.UUID, code: str
) -> VocabularyRecommendation:
    """按最近真实表现给下一轮建议（词数 / 题型 / 复习错词）。"""
    answers = _first_answers(session, student_id)
    practiceable = vocab_service.student_practiceable_word_ids(session, classroom_id)
    wrong_items = [
        item
        for item in vocab_service.wrong_word_items(session, student_id, practiceable)
        if item.practiceable
    ]
    wrong_items.sort(key=lambda item: (-item.wrong_count, item.headword))

    total = len(answers)
    correct = sum(1 for answer in answers if answer.is_correct)
    accuracy = (correct / total) if total else None
    basis: list[str] = []
    if total == 0:
        basis.append("no_history")
        word_count, prompt_types = 10, ["meaning", "en_zh"]
    elif accuracy is not None and accuracy < LOW_ACCURACY:
        basis.append("low_accuracy")
        word_count, prompt_types = 10, ["meaning", "cloze"]
    elif accuracy is not None and accuracy < HIGH_ACCURACY:
        basis.append("mid_accuracy")
        word_count, prompt_types = 15, ["en_zh", "zh_en", "cloze"]
    else:
        basis.append("high_accuracy")
        word_count, prompt_types = 20, ["en_zh", "zh_en", "cloze", "roots"]
    if wrong_items:
        basis.append("wrong_focus")
    if not practiceable:
        basis.append("no_practiceable_book")
        prompt_types = ["meaning"]
        word_count = 10

    return VocabularyRecommendation(
        classroom_code=code,
        generated_at=datetime.now(UTC),
        answered_total=total,
        correct_first_total=correct,
        accuracy=accuracy,
        basis=basis,
        suggested_word_count=word_count,
        suggested_prompt_types=prompt_types,
        focus_words=[
            VocabularyRecommendationFocus(
                word_id=item.word_id,
                headword=item.headword,
                meaning_zh=item.meaning_zh,
                wrong_count=item.wrong_count,
                practiceable=item.practiceable,
            )
            for item in wrong_items[:FOCUS_LIMIT]
        ],
    )


def _first_answers(session: Session, student_id: uuid.UUID) -> list[VocabularyAnswer]:
    """该学生计入统计的首答：练习（含自主轮）全部 + 已公布答案的测验。"""
    return list(
        session.exec(
            select(VocabularyAnswer)
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
                VocabularyAnswer.attempt_no == 1,  # type: ignore[arg-type]
                VocabularySession.kind != "placement",  # type: ignore[operator]
                (col(VocabularySession.assignment_id).is_(None))  # type: ignore[union-attr]
                | (col(VocabularyAssignment.mode) != "quiz")  # type: ignore[operator]
                | col(VocabularyAssignment.answers_published_at).is_not(None),  # type: ignore[union-attr]
            )
        ).all()
    )
