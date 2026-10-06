"""词汇 AI 备课与学情辅助接口。

    /vocabulary/ai/word-drafts        教师词条草稿生成（预览，不入库）
    /vocabulary/ai/word-drafts/import 教师确认草稿加入词库（不自动发布）
    /vocabulary/ai/word-explanation   学生单词结构化讲解（缓存，非聊天）
    /vocabulary/ai/session-insight    单次练习学情（只读本轮真实作答）
    /vocabulary/ai/overall-insight    整体学习建议（明确数量与时间范围）

红线：密钥不进前端；提示词不含学生身份；模型输出按不可信内容校验；
拼写对错仍由确定性规则判分；测验答案未公布时讲解/学情不绕过可见规则；
AI 失败/未配置一律 503，练习、交卷与确定性成绩不受影响。
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import SessionDep, StudentUserDep, TeacherUserDep
from app.api.routes.classes import _get_classroom, _student_profile_of
from app.models import (
    VocabularyAiExplanationRequest,
    VocabularyAiOverallInsight,
    VocabularyAiOverallInsightRequest,
    VocabularyAiSessionInsight,
    VocabularyAiSessionInsightRequest,
    VocabularyAiWordDraft,
    VocabularyAiWordDraftImportRequest,
    VocabularyAiWordDraftImportResult,
    VocabularyAiWordDraftsRequest,
    VocabularyAiWordDraftsResponse,
    VocabularyAiWordExplanation,
    VocabularyAssignment,
    VocabularySession,
    get_datetime_utc,
)
from app.services import vocab_ai, vocab_quiz
from app.services.vocabulary import session_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vocabulary-ai"])


def _ai_error_response(exc: Exception) -> HTTPException:
    logger.warning("vocab AI call failed: %s", exc, exc_info=True)
    return HTTPException(
        status_code=503,
        detail="AI 生成暂时不可用，请稍后再试；练习与成绩不受影响",
    )


# ── 教师：词条草稿生成与确认入库 ───────────────────────────────────


@router.post(
    "/vocabulary/ai/word-drafts", response_model=VocabularyAiWordDraftsResponse
)
def generate_word_drafts(
    current_user: TeacherUserDep,
    body: VocabularyAiWordDraftsRequest,
) -> Any:
    """AI 生成词条草稿：只返回预览，不入库、不发布；教师编辑确认后走
    import 接口加入自己的词库。level 校验沿用五级词库口径。"""
    vocab_ai.check_ai_rate_limit(f"teacher:{current_user.id}")
    vocab_ai.require_ai_configured()
    if body.level is not None:
        from app.models import VOCAB_LEVEL_ORDER

        if body.level not in VOCAB_LEVEL_ORDER:
            raise HTTPException(
                status_code=422,
                detail="级别无效，可选：" + "/".join(VOCAB_LEVEL_ORDER),
            )
    try:
        drafts, dropped = vocab_ai.generate_word_drafts(
            theme=body.theme.strip(),
            level=body.level,
            count=body.count,
            hint=body.hint,
        )
    except Exception as exc:  # ArkChatError / 解析失败等一律降级 503
        raise _ai_error_response(exc) from exc
    return VocabularyAiWordDraftsResponse(
        drafts=[VocabularyAiWordDraft.model_validate(d) for d in drafts],
        requested_count=body.count,
        generated_at=get_datetime_utc(),
        dropped_count=dropped,
    )


@router.post(
    "/vocabulary/ai/word-drafts/import",
    response_model=VocabularyAiWordDraftImportResult,
)
def import_word_drafts(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: VocabularyAiWordDraftImportRequest,
) -> Any:
    """确认草稿入库：教师可编辑后的草稿写入自己的班级词库（可接受拼写
    变体不从草稿接收）；与词库现有词条重复即跳过；不自动发布任务。"""
    try:
        added, skipped, total = vocab_ai.import_word_drafts(
            session,
            book_id=body.book_id,
            drafts=[d.model_dump() for d in body.drafts],
            current_user=current_user,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _ai_error_response(exc) from exc
    return VocabularyAiWordDraftImportResult(
        added=added, skipped=skipped, book_word_count=total
    )


# ── 学生：单词讲解 / 单次学情 / 整体建议 ───────────────────────────


def _unpublished_quiz_headwords(session: SessionDep, student_id: uuid.UUID) -> set[str]:
    """学生未公布答案的测验答卷里的词条拼写（讲解保护名单）。"""
    rounds = session.exec(
        select(VocabularySession).where(
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            VocabularySession.kind == "task",  # type: ignore[arg-type]
            col(VocabularySession.quiz_started_at).is_not(None),  # type: ignore[union-attr]
            VocabularySession.status == "submitted",  # type: ignore[arg-type]
        )
    ).all()
    blocked: set[str] = set()
    for vocab_session in rounds:
        assignment = (
            session.get(VocabularyAssignment, vocab_session.assignment_id)
            if vocab_session.assignment_id is not None
            else None
        )
        if assignment is None or assignment.mode != "quiz":
            continue
        if assignment.answers_published_at is not None:
            continue
        # 测验是任务轮：题单在任务快照里（会话自身无 snapshot_items）
        for item in assignment.snapshot_items or []:
            headword = item.get("headword")
            if isinstance(headword, str):
                blocked.add(headword.casefold())
    return blocked


@router.post(
    "/vocabulary/ai/word-explanation", response_model=VocabularyAiWordExplanation
)
def word_explanation(
    session: SessionDep,
    current_user: StudentUserDep,
    code: str,
    body: VocabularyAiExplanationRequest,
) -> Any:
    """单词结构化讲解（单轮，非聊天）：缓存 + 限流 + 降级。

    答案可见规则：该词出现在本人未公布答案的测验答卷里时不提供讲解
    （讲解含例句与常见误拼，可能变相揭示未公布拼写）。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    vocab_ai.check_ai_rate_limit(f"student:{student.id}")
    vocab_ai.require_ai_configured()

    headword = body.headword.strip()
    meaning_zh = body.meaning_zh.strip()
    if headword.casefold() in _unpublished_quiz_headwords(session, student.id):
        raise HTTPException(
            status_code=422,
            detail="测验答案公布后才能查看这个词的讲解",
        )

    cache_key = vocab_ai.explanation_cache_key(headword, meaning_zh)
    fingerprint = vocab_ai.explanation_fingerprint(headword, meaning_zh)
    payload, created_at, stale = vocab_ai.get_cached_insight(
        session, cache_key, fingerprint
    )
    if payload is not None and not stale and not body.force:
        return VocabularyAiWordExplanation.model_validate(
            {
                **payload,
                "generated_at": created_at or get_datetime_utc(),
                "cached": True,
                "stale": False,
            }
        )
    try:
        fresh = vocab_ai.build_explanation_payload(
            headword, meaning_zh, body.part_of_speech
        )
    except Exception as exc:
        raise _ai_error_response(exc) from exc
    vocab_ai.save_insight_cache(
        session,
        cache_key=cache_key,
        kind="explanation",
        student_id=student.id,
        payload=fresh,
        fingerprint=fingerprint,
    )
    return VocabularyAiWordExplanation.model_validate(
        {**fresh, "generated_at": get_datetime_utc(), "cached": False, "stale": False}
    )


@router.post(
    "/vocabulary/ai/session-insight", response_model=VocabularyAiSessionInsight
)
def session_insight(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    body: VocabularyAiSessionInsightRequest,
) -> Any:
    """单次练习学情：只使用本轮真实作答；测验答案未公布时不提供
    （不得绕过答案可见规则）。缓存按作答指纹判定新旧。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    vocab_ai.check_ai_rate_limit(f"student:{student.id}")
    vocab_ai.require_ai_configured()

    vocab_session = session.get(VocabularySession, body.session_id)
    if vocab_session is None or vocab_session.student_id != student.id:
        # 他人的/不存在的一律 404
        raise HTTPException(status_code=404, detail="练习记录不存在")
    assignment = (
        session.get(VocabularyAssignment, vocab_session.assignment_id)
        if vocab_session.assignment_id is not None
        else None
    )
    is_quiz = assignment is not None and assignment.mode == "quiz"
    if is_quiz and assignment is not None:
        if assignment.answers_published_at is None:
            raise HTTPException(
                status_code=422,
                detail="测验答案公布后才能生成本次学情分析",
            )
        vocab_quiz.settle_due_sessions(session, assignment)
    snapshot_items = session_snapshot(session, vocab_session)
    cache_key = f"session-insight:{vocab_session.id}"
    fingerprint = vocab_ai.session_insight_fingerprint(session, vocab_session.id)
    payload, created_at, stale = vocab_ai.get_cached_insight(
        session, cache_key, fingerprint
    )
    if payload is not None and not stale and not body.force:
        return VocabularyAiSessionInsight.model_validate(
            {
                **payload,
                "generated_at": created_at or get_datetime_utc(),
                "cached": True,
                "stale": False,
            }
        )
    try:
        fresh = vocab_ai.generate_session_insight(
            session, vocab_session, snapshot_items
        )
    except Exception as exc:
        raise _ai_error_response(exc) from exc
    vocab_ai.save_insight_cache(
        session,
        cache_key=cache_key,
        kind="session-insight",
        student_id=student.id,
        payload=fresh,
        fingerprint=fingerprint,
    )
    return VocabularyAiSessionInsight.model_validate(
        {**fresh, "generated_at": get_datetime_utc(), "cached": False, "stale": False}
    )


@router.post(
    "/vocabulary/ai/overall-insight", response_model=VocabularyAiOverallInsight
)
def overall_insight(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    body: VocabularyAiOverallInsightRequest,
) -> Any:
    """整体学习建议：最近 limit 轮、days 天内的历史记录（未公布测验
    作答不计入）；缓存按窗口内作答指纹判定新旧。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    vocab_ai.check_ai_rate_limit(f"student:{student.id}")
    vocab_ai.require_ai_configured()

    cache_key = f"overall-insight:{student.id}:{body.limit}:{body.days}"
    (
        fingerprint,
        from_time,
        to_time,
        rounds_used,
        answered_total,
        wrong_pool,
        _scoped_count,
    ) = vocab_ai.overall_fingerprint(session, student.id, body.limit, body.days)
    payload, created_at, stale = vocab_ai.get_cached_insight(
        session, cache_key, fingerprint
    )
    if payload is not None and not stale and not body.force:
        return VocabularyAiOverallInsight.model_validate(
            {
                **payload,
                "generated_at": created_at or get_datetime_utc(),
                "cached": True,
                "stale": False,
            }
        )
    if rounds_used == 0 or not wrong_pool:
        raise HTTPException(
            status_code=422,
            detail="这个时间范围内还没有可分析的练习记录",
        )
    # 缓存 payload 是 JSON：时间一律 ISO 字符串（响应模型会再解析）
    scope_meta: dict[str, object] = {
        "answered_count": answered_total,
        "rounds": rounds_used,
        "days": body.days,
        "from_time": from_time.isoformat() if from_time else None,
        "to_time": to_time.isoformat() if to_time else None,
    }
    # 证据摘要（限条数，防提示词过长）：错词池全量 + 每轮对错计数
    try:
        fresh = vocab_ai.generate_overall_insight(
            scope_meta=scope_meta,
            wrong_pool=wrong_pool,
            evidence_digest=[
                {
                    "word": w["headword"],
                    "meaning": w["meaning_zh"],
                    "your_answer": w["your_answer"],
                    "correct": w["correct_spelling"],
                }
                for w in wrong_pool[:20]
            ],
        )
    except Exception as exc:
        raise _ai_error_response(exc) from exc
    vocab_ai.save_insight_cache(
        session,
        cache_key=cache_key,
        kind="overall-insight",
        student_id=student.id,
        payload=fresh,
        fingerprint=fingerprint,
    )
    return VocabularyAiOverallInsight.model_validate(
        {**fresh, "generated_at": get_datetime_utc(), "cached": False, "stale": False}
    )
