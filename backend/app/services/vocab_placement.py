"""粗分档自适应小测（placement）域逻辑。

口径与边界（产品需求 2026-11-24，#517 批次）：

- **探针式粗分档**：只给「建议起点级别 + 推荐词库 + 说明」，不是精准定级、
  不是考试分数、不发认证；不写学生等级字段、不锁任务难度。
- **独立会话**：``kind="placement"``，不计入教师任务/自主练习统计，不写 FSRS
  复习状态，不推进农场 XP；本服务不调用 ``vocabulary_review`` /
  ``vocabulary_farm`` 的任何写接口。
- **题源**：本班可练词库中 ``review_status=approved`` 且 active 的词（复用
  ``student_practiceable_word_ids``），按五级归属映射到四档；无五级归属的词
  不进本测题池。选项全部来自真实 approved 词条，不硬造题。
- **自适应规则**（固定、可测试、可解释）：从 PET 档起步；答对升一档、答错降
  一档（边界钳制）；默认最多 12 题；最终建议 = 至少 2 次正确作答的最高档，
  一档都没达到则建议 KET。
- **素材不足**：可用题量不足 12 按实际题量降级并带限制说明；可用映射词少于
  4 个（组不成四选一）直接 422，不生成假题。
"""

import copy
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    LIMITATION_MATERIAL_LIMITED,
    LIMITATION_NONE,
    PLACEMENT_BAND_LEVELS,
    PLACEMENT_BAND_ORDER,
    PLACEMENT_BAND_PRIMARY_LEVEL,
    PLACEMENT_DEFAULT_TOTAL,
    PLACEMENT_KIND,
    PLACEMENT_MIN_CHOICE_WORDS,
    PLACEMENT_PASS_CORRECT,
    PLACEMENT_START_BAND,
    PlacementChoice,
    PlacementQuestion,
    PlacementResultPublic,
    Student,
    VocabPlacementResult,
    VocabularyAnswer,
    VocabularyBook,
    VocabularyBookItem,
    VocabularySession,
    VocabularyWord,
)
from app.services import vocab_levels as vocab_levels_service
from app.services import vocabulary as vocab_service
from app.services import vocabulary_prompt_types as prompt_types_mod

# 会话快照 JSON 结构：snapshot_items[0] = 运行元数据，其后为逐题快照
_META_KEY = "_meta"


# ── 纯逻辑：档位映射与收敛规则（单测直接覆盖）─────────────────────────────


def level_to_band(level: str | None) -> str | None:
    """五级级别 → 本测档位；未归属 / 未知级别返回 None（不进题池）。"""
    if level is None:
        return None
    for band, levels in PLACEMENT_BAND_LEVELS.items():
        if level in levels:
            return band
    return None


def next_band(current: str, is_correct: bool) -> str:
    """答对升一档、答错降一档；顶档/底档边界钳制。"""
    idx = PLACEMENT_BAND_ORDER.index(current)
    idx += 1 if is_correct else -1
    idx = max(0, min(len(PLACEMENT_BAND_ORDER) - 1, idx))
    return PLACEMENT_BAND_ORDER[idx]


def recommend_band(band_correct: dict[str, int]) -> str:
    """最终建议档：至少 ``PLACEMENT_PASS_CORRECT`` 次正确的最高档；否则 KET。"""
    for band in reversed(PLACEMENT_BAND_ORDER):
        if band_correct.get(band, 0) >= PLACEMENT_PASS_CORRECT:
            return band
    return PLACEMENT_BAND_ORDER[0]


def _band_preference(current: str) -> list[str]:
    """当前档优先，其余档按距离由近到远排（当前档无可用词时兜底外移）。"""
    idx = PLACEMENT_BAND_ORDER.index(current)
    ordered = [idx]
    delta = 1
    while len(ordered) < len(PLACEMENT_BAND_ORDER):
        for candidate in (idx - delta, idx + delta):
            if 0 <= candidate < len(PLACEMENT_BAND_ORDER) and candidate not in ordered:
                ordered.append(candidate)
        delta += 1
    return [PLACEMENT_BAND_ORDER[i] for i in ordered]


def _stable_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


# ── 题池加载 ────────────────────────────────────────────────────────────


def _practiceable_grouped(
    session: Session, classroom_id: uuid.UUID
) -> dict[str, list[VocabularyWord]]:
    """本班可练 approved active 词按四档分组；无五级归属的词剔除。"""
    grouped: dict[str, list[VocabularyWord]] = {
        band: [] for band in PLACEMENT_BAND_ORDER
    }
    practiceable_ids = vocab_service.student_practiceable_word_ids(
        session, classroom_id
    )
    if not practiceable_ids:
        return grouped
    words = list(
        session.exec(
            select(VocabularyWord).where(
                col(VocabularyWord.id).in_(practiceable_ids)  # type: ignore[operator]
            )
        ).all()
    )
    level_map = vocab_levels_service.effective_level_map(
        session, [w.headword for w in words]
    )
    for word in words:
        info = level_map.get(vocab_service.normalize_spelling(word.headword))
        band = level_to_band(info[0] if info else None)
        if band is not None:
            grouped[band].append(word)
    return grouped


def _all_pool_words(grouped: dict[str, list[VocabularyWord]]) -> list[VocabularyWord]:
    return [word for words in grouped.values() for word in words]


def _option(word: VocabularyWord) -> dict[str, object]:
    return {
        "word_id": str(word.id),
        "headword": word.headword,
        "part_of_speech": word.part_of_speech,
        "meaning_zh": word.meaning_zh,
    }


def _build_question(
    item_index: int,
    band: str,
    word: VocabularyWord,
    pool: list[VocabularyWord],
    seed: str,
) -> dict[str, object]:
    """英译中四选一：正确项 + 三个释义不同的真实干扰项，顺序按 ID 稳定打散。"""
    correct_meaning = str(word.meaning_zh).strip()
    distractors = [
        candidate
        for candidate in pool
        if candidate.id != word.id
        and str(candidate.meaning_zh).strip() != correct_meaning
    ]
    distractors.sort(
        key=lambda candidate: _stable_seed(seed, "distractor", str(candidate.id))
    )
    distractors = distractors[:3]
    options = [_option(candidate) for candidate in distractors]
    insert_at = _stable_seed(seed, "pos", str(word.id)) % (len(options) + 1)
    options.insert(insert_at, _option(word))
    return {
        "word_id": str(word.id),
        "band": band,
        "headword": word.headword,
        "part_of_speech": word.part_of_speech,
        "meaning_zh": word.meaning_zh,
        "choices": options,
        "item_index": item_index,
    }


def _pick_word(
    grouped: dict[str, list[VocabularyWord]],
    asked_ids: set[str],
    current_band: str,
    seed: str,
) -> tuple[str | None, VocabularyWord | None]:
    """按档位偏好取一个未用过的词；池尽返回 (None, None)。"""
    for band in _band_preference(current_band):
        candidates = [
            word for word in grouped.get(band, []) if str(word.id) not in asked_ids
        ]
        if candidates:
            candidates.sort(key=lambda word: _stable_seed(seed, band, str(word.id)))
            return band, candidates[0]
    return None, None


# ── 会话快照读写 ────────────────────────────────────────────────────────


def _meta(vocab_session: VocabularySession) -> dict[str, Any]:
    items = vocab_session.snapshot_items or []
    if (
        not items
        or not isinstance(items[0], dict)
        or items[0].get(_META_KEY) is not True
    ):
        raise HTTPException(status_code=422, detail="placement_session_invalid")
    return items[0]  # type: ignore[return-value]


def _questions(vocab_session: VocabularySession) -> list[dict[str, object]]:
    items = vocab_session.snapshot_items or []
    return [item for item in items[1:] if isinstance(item, dict)]


def _persist_snapshot(
    vocab_session: VocabularySession,
    meta: dict[str, Any],
    questions: list[dict[str, object]],
) -> None:
    # JSON 列嵌套对象原地突变不会被 ORM 标记脏；深拷贝成全新结构再回写，
    # 保证本轮 asked/档位/下一题稳定落库（否则状态会滞后一轮）。
    vocab_session.snapshot_items = copy.deepcopy([meta, *questions])


def _question_view(question: dict[str, Any] | None) -> PlacementQuestion | None:
    if question is None:
        return None
    choices = [
        PlacementChoice(
            word_id=uuid.UUID(str(choice["word_id"])),
            headword=str(choice["headword"]),
            part_of_speech=choice.get("part_of_speech"),
            meaning_zh=str(choice["meaning_zh"]),
        )
        for choice in question["choices"]
    ]
    return PlacementQuestion(
        item_index=int(question["item_index"]),
        band=str(question["band"]),
        headword=str(question["headword"]),
        part_of_speech=question.get("part_of_speech"),
        choices=choices,
    )


def _answered_count(session: Session, vocab_session: VocabularySession) -> int:
    return len(
        session.exec(
            select(VocabularyAnswer).where(
                VocabularyAnswer.session_id == vocab_session.id  # type: ignore[arg-type]
            )
        ).all()
    )


def _result_for_session(
    session: Session, session_id: uuid.UUID
) -> VocabPlacementResult | None:
    """按会话取回已落库的结果（幂等重放 / 收尾后回执用）；无记录返回 None。"""
    return session.exec(
        select(VocabPlacementResult).where(
            VocabPlacementResult.session_id == session_id  # type: ignore[arg-type]
        )
    ).first()


def _view_payload(
    session: Session,
    vocab_session: VocabularySession,
    result: VocabPlacementResult | None = None,
) -> dict[str, Any]:
    meta = _meta(vocab_session)
    questions = _questions(vocab_session)
    answered = _answered_count(session, vocab_session)
    current_question = questions[answered] if answered < len(questions) else None
    limitation = meta["limitation"]
    return {
        "session_id": vocab_session.id,
        "status": vocab_session.status,
        "planned_total": int(meta["planned_total"]),
        "answered_count": answered,
        "degraded": bool(meta["degraded"]),
        "limitation": limitation if limitation != LIMITATION_NONE else None,
        "question": _question_view(current_question),
        "result": _public(result) if result else None,
    }


# ── 开始 / 续做 ─────────────────────────────────────────────────────────


def start_or_resume(
    session: Session, classroom_id: uuid.UUID, student: Student
) -> dict[str, Any]:
    """开始一次粗分档小测；已有进行中轮次直接续做（刷新/重复点击不重复开轮）。"""
    resume = session.exec(
        select(VocabularySession).where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularySession.student_id == student.id,  # type: ignore[arg-type]
            VocabularySession.kind == PLACEMENT_KIND,  # type: ignore[arg-type]
            VocabularySession.status == "in_progress",  # type: ignore[arg-type]
        )
    ).first()
    if resume is not None:
        return _view_payload(session, resume)

    grouped = _practiceable_grouped(session, classroom_id)
    pool = _all_pool_words(grouped)
    if len(pool) < PLACEMENT_MIN_CHOICE_WORDS:
        raise HTTPException(
            status_code=422,
            detail="placement_insufficient_words",
        )

    planned_total = min(PLACEMENT_DEFAULT_TOTAL, len(pool))
    degraded = len(pool) < PLACEMENT_DEFAULT_TOTAL
    limitation = LIMITATION_MATERIAL_LIMITED if degraded else LIMITATION_NONE
    meta: dict[str, Any] = {
        _META_KEY: True,
        "planned_total": planned_total,
        "current_band": PLACEMENT_START_BAND,
        "degraded": degraded,
        "limitation": limitation,
    }
    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student.id,
        kind=PLACEMENT_KIND,
        mode=PLACEMENT_KIND,
        status="in_progress",
        snapshot_items=[meta],
    )
    session.add(vocab_session)
    session.commit()
    session.refresh(vocab_session)

    band, word = _pick_word(grouped, set(), meta["current_band"], str(vocab_session.id))
    if word is None:  # 池尽兜底（理论上被 422 门禁挡住）
        raise HTTPException(status_code=422, detail="placement_insufficient_words")
    assert band is not None
    questions = [_build_question(0, band, word, pool, str(vocab_session.id))]
    _persist_snapshot(vocab_session, meta, questions)
    session.add(vocab_session)
    session.commit()
    session.refresh(vocab_session)
    return _view_payload(session, vocab_session)


# ── 作答 ────────────────────────────────────────────────────────────────


def submit_answer(
    session: Session,
    vocab_session: VocabularySession,
    *,
    item_index: int,
    answer_raw: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """提交首答（每题一次）；返回正误 + 下一题或最终建议。

    本路径刻意不调用 FSRS 调度与农场记账；作答记录仅服务本测判分与历史。
    """
    replay = vocab_service.recognize_answer_replay(
        session,
        vocab_session,
        item_index=item_index,
        prompt_type="en_zh",
        answer_raw=answer_raw,
        idempotency_key=idempotency_key,
    )

    meta = _meta(vocab_session)
    questions = _questions(vocab_session)

    if replay is not None:
        # 幂等重放：会话已收尾时带回已落库结果，避免前端重试拿不到建议而卡住。
        result = None
        if vocab_session.status == "submitted":
            result = _result_for_session(session, vocab_session.id)
        return _answer_payload(
            session, vocab_session, replay, questions[replay.item_index], result
        )

    if vocab_session.status != "in_progress":
        raise HTTPException(status_code=422, detail="placement_session_finished")

    existing = session.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == vocab_session.id,  # type: ignore[arg-type]
            VocabularyAnswer.item_index == item_index,
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=422, detail="placement_per_item_once")

    if item_index < 0 or item_index >= len(questions):
        raise HTTPException(status_code=422, detail="placement_question_not_ready")

    question = questions[item_index]
    is_correct = prompt_types_mod.choice_answer_matches(answer_raw, question)
    normalized = vocab_service.normalize_spelling(answer_raw)
    answer_row = VocabularyAnswer(
        session_id=vocab_session.id,
        item_index=item_index,
        attempt_no=1,
        prompt_type="en_zh",
        answer_raw=answer_raw[:255],
        answer_normalized=normalized[:255],
        is_correct=is_correct,
        word_id=uuid.UUID(str(question["word_id"])),
        headword=str(question["headword"])[:64],
        meaning_zh=str(question["meaning_zh"])[:255],
        idempotency_key=idempotency_key,
    )
    session.add(answer_row)

    meta["current_band"] = next_band(meta["current_band"], is_correct)
    _persist_snapshot(vocab_session, meta, questions)
    session.add(vocab_session)
    session.commit()
    session.refresh(answer_row)
    session.refresh(vocab_session)

    grouped = _practiceable_grouped(session, vocab_session.classroom_id)
    # 已问词 = 已生成题目覆盖的词（含当前题）；直接从题单推导，不另存冗余列表
    asked_ids = {str(q["word_id"]) for q in questions}
    answered_count = item_index + 1
    next_band_value, next_word = _pick_word(
        grouped, asked_ids, meta["current_band"], str(vocab_session.id)
    )

    if answered_count >= int(meta["planned_total"]) or next_word is None:
        result = _finalize(session, vocab_session, grouped)
        return _answer_payload(session, vocab_session, answer_row, question, result)

    assert next_band_value is not None
    next_question = _build_question(
        len(questions),
        next_band_value,
        next_word,
        _all_pool_words(grouped),
        str(vocab_session.id),
    )
    questions.append(next_question)
    _persist_snapshot(vocab_session, meta, questions)
    session.add(vocab_session)
    session.commit()
    session.refresh(vocab_session)
    return _answer_payload(session, vocab_session, answer_row, question)


def _answer_payload(
    session: Session,
    vocab_session: VocabularySession,
    answer: VocabularyAnswer,
    question: dict[str, object],
    result: VocabPlacementResult | None = None,
) -> dict[str, Any]:
    payload = _view_payload(session, vocab_session, result)
    payload.update(
        {
            "item_index": answer.item_index,
            "is_correct": answer.is_correct,
            "correct_headword": str(question["headword"]),
            "meaning_zh": str(question["meaning_zh"]),
        }
    )
    return payload


# ── 收尾：建议档 + 推荐词库 ──────────────────────────────────────────────


def _recommend_book(
    session: Session,
    grouped: dict[str, list[VocabularyWord]],
    recommended_band: str,
) -> tuple[uuid.UUID | None, str | None]:
    """推荐词库：含最多建议档词条的可见 active 词库；兜底含最多 approved 词者。"""
    band_words = {word.id for word in grouped.get(recommended_band, [])}
    all_words = {word.id for words in grouped.values() for word in words}
    if not all_words:
        return None, None
    rows = session.exec(
        select(VocabularyBookItem.book_id, VocabularyBookItem.word_id).where(
            col(VocabularyBookItem.word_id).in_(all_words)  # type: ignore[operator]
        )
    ).all()
    books = {
        book.id: book
        for book in session.exec(
            select(VocabularyBook).where(VocabularyBook.status == "active")  # type: ignore[arg-type]
        ).all()
    }
    band_score: dict[uuid.UUID, int] = {}
    total_score: dict[uuid.UUID, int] = {}
    for book_id, word_id in rows:
        if book_id not in books:
            continue
        total_score[book_id] = total_score.get(book_id, 0) + 1
        if word_id in band_words:
            band_score[book_id] = band_score.get(book_id, 0) + 1
    if not total_score:
        return None, None
    best = max(total_score, key=lambda bid: (band_score.get(bid, 0), total_score[bid]))
    return best, books[best].title


def _finalize(
    session: Session,
    vocab_session: VocabularySession,
    grouped: dict[str, list[VocabularyWord]],
) -> VocabPlacementResult:
    answers = list(
        session.exec(
            select(VocabularyAnswer).where(
                VocabularyAnswer.session_id == vocab_session.id  # type: ignore[arg-type]
            )
        ).all()
    )
    questions = _questions(vocab_session)
    question_band = {str(q["word_id"]): str(q["band"]) for q in questions}
    band_correct: dict[str, int] = {}
    for answer in answers:
        if answer.is_correct:
            band = question_band.get(str(answer.word_id))
            if band is not None:
                band_correct[band] = band_correct.get(band, 0) + 1

    recommended = recommend_band(band_correct)
    book_id, book_title = _recommend_book(session, grouped, recommended)
    meta = _meta(vocab_session)
    result = VocabPlacementResult(
        classroom_id=vocab_session.classroom_id,
        student_id=vocab_session.student_id,
        session_id=vocab_session.id,
        recommended_band=recommended,
        recommended_level=PLACEMENT_BAND_PRIMARY_LEVEL[recommended],
        recommended_book_id=book_id,
        recommended_book_title=book_title,
        question_count=len(answers),
        answered_count=len(answers),
        correct_count=sum(1 for answer in answers if answer.is_correct),
        limitation=str(meta["limitation"]),
        submitted_at=datetime.now(UTC),
    )
    vocab_session.status = "submitted"
    vocab_session.submitted_at = datetime.now(UTC)
    session.add(result)
    session.add(vocab_session)
    session.commit()
    session.refresh(result)
    return result


# ── 历史与教师只读列表 ──────────────────────────────────────────────────


def student_history(
    session: Session, student_id: uuid.UUID
) -> list[VocabPlacementResult]:
    """学生本人全部测次（重测保留历史，按时间倒序）。"""
    return list(
        session.exec(
            select(VocabPlacementResult)
            .where(VocabPlacementResult.student_id == student_id)  # type: ignore[arg-type]
            .order_by(col(VocabPlacementResult.submitted_at).desc())
        ).all()
    )


def student_history_public(
    session: Session, student: Student
) -> list[PlacementResultPublic]:
    """本人历史的公开视图（带学生展示名；重测追加，按时间倒序）。"""
    return [_to_public(row, student) for row in student_history(session, student.id)]


def teacher_results(
    session: Session, classroom_id: uuid.UUID
) -> list[PlacementResultPublic]:
    """教师/管理员只读：本班学生最近一次测次（重测不覆盖旧记录，仅展示最新）。"""
    rows = list(
        session.exec(
            select(VocabPlacementResult)
            .where(VocabPlacementResult.classroom_id == classroom_id)  # type: ignore[arg-type]
            .order_by(col(VocabPlacementResult.submitted_at).desc())
        ).all()
    )
    latest: dict[uuid.UUID, VocabPlacementResult] = {}
    for row in rows:
        latest.setdefault(row.student_id, row)
    students = {
        student.id: student
        for student in session.exec(
            select(Student).where(Student.classroom_id == classroom_id)  # type: ignore[arg-type]
        ).all()
    }
    publics = [_to_public(row, students.get(row.student_id)) for row in latest.values()]
    publics.sort(
        key=lambda item: (item.display_name, item.submitted_at or datetime.min)
    )
    return publics


def _public(
    result: VocabPlacementResult | None, student: Student | None = None
) -> PlacementResultPublic | None:
    if result is None:
        return None
    return _to_public(result, student)


def _to_public(
    result: VocabPlacementResult, student: Student | None = None
) -> PlacementResultPublic:
    return PlacementResultPublic(
        id=result.id,
        student_id=result.student_id,
        display_name=student.display_name if student else "–",
        suffix=student.suffix if student else None,
        recommended_band=result.recommended_band,
        recommended_level=result.recommended_level,
        recommended_book_id=result.recommended_book_id,
        recommended_book_title=result.recommended_book_title,
        question_count=result.question_count,
        answered_count=result.answered_count,
        correct_count=result.correct_count,
        limitation=result.limitation,
        submitted_at=result.submitted_at,
    )
