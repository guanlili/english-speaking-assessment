"""词汇 AI 备课与学情辅助：提示词、输出校验、缓存指纹、限流、降级。

红线（设计文档口径）：
- 拼写对错始终由确定性规则判分，AI 不参与判分；
- 模型输出按不可信内容处理——长度截断、格式校验、薄弱词必须映射到
  真实作答证据（模型虚构的词一律丢弃）；
- 提示词只携带词条与作答内容，不含学生姓名/学号/邮箱；
- 未配置密钥/调用失败时抛 ArkChatError，由路由层降级为 503——练习、
  交卷与确定性成绩不受任何影响；
- 全部为用户主动生成（点击按钮），不在作答后自动调用。
"""

import hashlib
import json
import threading
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    VOCAB_AI_RATE_LIMIT,
    VOCAB_AI_RATE_WINDOW_S,
    User,
    VocabularyAiCache,
    VocabularyAnswer,
    VocabularySession,
    get_datetime_utc,
)
from app.scoring.ark_client import ArkChatClient, ArkChatError

# ── 限流（与登录限流同模式的进程内滑动窗口）────────────────────────

_rate_buckets: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()
_RATE_PRUNE_THRESHOLD = 4096


def check_ai_rate_limit(bucket: str) -> None:
    """每用户滑动窗口限流；超限 429（带 Retry-After）。"""
    now = time.monotonic()
    with _rate_lock:
        if len(_rate_buckets) > _RATE_PRUNE_THRESHOLD:
            cutoff = now - VOCAB_AI_RATE_WINDOW_S
            for key in [
                k
                for k, window in _rate_buckets.items()
                if not window or window[-1] < cutoff
            ]:
                _rate_buckets.pop(key, None)
        window = _rate_buckets.get(bucket, [])
        cutoff = now - VOCAB_AI_RATE_WINDOW_S
        while window and window[0] < cutoff:
            window.pop(0)
        if len(window) >= VOCAB_AI_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="AI 生成次数已达上限（每小时 10 次），请稍后再试",
                headers={"Retry-After": str(VOCAB_AI_RATE_WINDOW_S)},
            )
        window.append(now)
        _rate_buckets[bucket] = window  # 首次出现的桶要存回（get 的默认值不落盘）


def _chat(system: str, user: str, temperature: float = 0.4) -> str:
    """模型调用唯一入口（测试通过 monkeypatch 本函数注入模拟响应）。"""
    from app.core.config import settings

    client = ArkChatClient(
        api_key=settings.ARK_API_KEY, model=settings.ARK_RUBRIC_MODEL
    )
    return client.chat(system=system, user=user, temperature=temperature)


def ai_configured() -> bool:
    from app.core.config import settings

    return bool(settings.ARK_API_KEY)


def require_ai_configured() -> None:
    if not ai_configured():
        raise HTTPException(
            status_code=503,
            detail="AI 功能未配置，练习与成绩不受影响；请联系管理员",
        )


def parse_model_json_object(content: str) -> dict:
    """容错解析模型输出的 JSON 对象（剥 markdown 栅栏）。"""
    from app.scoring.ark_client import parse_json_payload

    return parse_json_payload(content)


def _clean_str(value: object, max_len: int, str_only: bool = False) -> str | None:
    """不可信字符串：截断 + 空串归 None（渲染层再按纯文本转义）。

    str_only=True 时只接受真字符串（列表字段里的数字/布尔一律丢弃）。
    """
    if value is None:
        return None
    if str_only and not isinstance(value, str):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _sha(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:32]


# ── 教师词条草稿 ───────────────────────────────────────────────────

DRAFT_SYSTEM_PROMPT = (
    "You draft vocabulary entries for Chinese secondary school students "
    "learning English. Entries must fit the requested topic and level, be "
    "real, common English words or phrases, and be useful for spelling "
    "practice. Never invent accepted spelling variants. Respond with ONLY "
    "a JSON array (no markdown) of objects: "
    '{"headword": "<English word>", "part_of_speech": "<pos or null>", '
    '"meaning_zh": "<简体中文释义>", "meaning_en": "<English meaning or null>", '
    '"example_en": "<short example sentence or null>"}'
)


def build_draft_user_prompt(
    theme: str, level: str | None, count: int, hint: str | None
) -> str:
    level_names = {
        "KET": "Cambridge KET (A2) vocabulary",
        "PET": "Cambridge PET (B1) vocabulary",
        "ACADEMIC": "academic word list",
        "CET4": "CET-4 college vocabulary",
        "IELTS_TOEFL": "IELTS/TOEFL vocabulary",
    }

    lines = [f"Topic: {theme}"]
    if level:
        lines.append(f"Target level: {level} — {level_names.get(level, level)}")
    lines.append(f"Generate exactly {count} different entries.")
    lines.append(
        "Each entry: headword (single word or short phrase), part of speech, "
        "简体中文释义, simple English meaning, one short example sentence."
    )
    if hint:
        lines.append(f"Extra guidance from the teacher: {hint}")
    return "\n".join(lines)


def generate_word_drafts(
    theme: str,
    level: str | None,
    count: int,
    hint: str | None,
) -> tuple[list[dict[str, object]], int]:
    """生成词条草稿：格式/数量/重复检查后返回（不入库；dropped 透明展示）。"""
    content = _chat(
        system=DRAFT_SYSTEM_PROMPT,
        user=build_draft_user_prompt(theme, level, count, hint),
        temperature=0.6,
    )
    from app.scoring.ark_client import parse_json_list

    items = parse_json_list(content)
    drafts: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    dropped = 0
    for item in items:
        if not isinstance(item, dict) or len(drafts) >= count:
            dropped += 1
            continue
        headword = _clean_str(item.get("headword"), 64)
        meaning_zh = _clean_str(item.get("meaning_zh"), 255)
        if not headword or not meaning_zh:
            dropped += 1
            continue
        key = (headword.casefold(), meaning_zh)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        drafts.append(
            {
                "headword": headword,
                "part_of_speech": _clean_str(item.get("part_of_speech"), 32),
                "meaning_zh": meaning_zh,
                "meaning_en": _clean_str(item.get("meaning_en"), 255),
                "example_en": _clean_str(item.get("example_en"), 512),
            }
        )
    if not drafts:
        raise ArkChatError("模型没有返回可用的词条草稿")
    return drafts, dropped


def import_word_drafts(
    session: Session,
    *,
    book_id: uuid.UUID,
    drafts: list[dict[str, object]],
    current_user: User,
) -> tuple[int, int, int]:
    """教师确认入库：剥离不可信字段（accepted_spellings 等），走既有加词
    去重语义（headword+meaning_zh 与词库现有词条重复即跳过）。
    current_user = 完整教师用户（编辑权校验沿用既有规则）。"""
    from app.api.routes.vocabulary import (
        MAX_BOOK_WORDS,
        _add_words_to_book,
        _get_book,
        _require_book_editor,
    )

    book = _get_book(session, book_id)
    _require_book_editor(book, current_user)
    if book.status != "active":
        raise HTTPException(status_code=422, detail="词库已归档，不能加词")
    if len(drafts) > MAX_BOOK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"单次最多加入 {MAX_BOOK_WORDS} 个词"
        )
    from app.models import VocabularyWordIn

    words_in = [
        VocabularyWordIn(
            headword=str(d.get("headword", "")).strip(),
            part_of_speech=_clean_str(d.get("part_of_speech"), 32),
            meaning_zh=str(d.get("meaning_zh", "")).strip(),
            meaning_en=_clean_str(d.get("meaning_en"), 255),
            example_en=_clean_str(d.get("example_en"), 512),
            # accepted_spellings 不从 AI 草稿接收——只能由教师显式维护
        )
        for d in drafts
        if str(d.get("headword", "")).strip() and str(d.get("meaning_zh", "")).strip()
    ]
    valid = [w for w in words_in if w.headword and w.meaning_zh]
    added = _add_words_to_book(session, book, valid)
    from app.api.routes.vocabulary import _book_word_count

    counts = _book_word_count(session, [book.id])
    return added, len(valid) - added, counts.get(book.id, 0)


# ── 单词讲解（学生）────────────────────────────────────────────────

EXPLANATION_SYSTEM_PROMPT = (
    "You explain English vocabulary to Chinese secondary school students. "
    "Given one word and its Chinese meaning, respond with ONLY a JSON "
    "object (no markdown): "
    '{"meanings": ["<简体中文词义，最多3条>"], '
    '"common_misspellings": ["<中国学生常见误拼，最多4条，仅拼写不含解释>"], '
    '"memory_tips": ["<简体中文记忆提示，最多3条，每条不超过40字>"], '
    '"examples": ["<short English example sentences, max 2>"]}. '
    "Be accurate and concise; never add extra fields."
)


def build_explanation_user_prompt(
    headword: str, meaning_zh: str, part_of_speech: str | None
) -> str:
    lines = [f"Word: {headword}", f"Known Chinese meaning: {meaning_zh}"]
    if part_of_speech:
        lines.append(f"Part of speech: {part_of_speech}")
    return "\n".join(lines)


def explanation_cache_key(headword: str, meaning_zh: str) -> str:
    return f"explain:{_sha(headword.casefold(), meaning_zh.strip())}"


def build_explanation_payload(
    headword: str, meaning_zh: str, part_of_speech: str | None
) -> dict[str, object]:
    content = _chat(
        system=EXPLANATION_SYSTEM_PROMPT,
        user=build_explanation_user_prompt(headword, meaning_zh, part_of_speech),
        temperature=0.3,
    )
    data = parse_model_json_object(content)
    meanings = [
        m
        for m in (
            _clean_str(v, 120, str_only=True) for v in data.get("meanings", []) or []
        )
        if m
    ][:3] or [meaning_zh]
    misspellings = [
        m
        for m in (
            _clean_str(v, 64, str_only=True)
            for v in data.get("common_misspellings", []) or []
        )
        if m
    ][:4]
    tips = [
        t_
        for t_ in (
            _clean_str(v, 80, str_only=True) for v in data.get("memory_tips", []) or []
        )
        if t_
    ][:3]
    examples = [
        e
        for e in (
            _clean_str(v, 200, str_only=True) for v in data.get("examples", []) or []
        )
        if e
    ][:2]
    return {
        "headword": headword,
        "meaning_zh": meaning_zh,
        "meanings": meanings,
        "common_misspellings": misspellings,
        "memory_tips": tips,
        "examples": examples,
    }


def explanation_fingerprint(headword: str, meaning_zh: str) -> str:
    # 讲解是词条级静态内容：指纹=内容本身（词库编辑后 force 可刷新）
    return _sha("static", headword.casefold(), meaning_zh.strip())


# ── 学情分析（学生；只使用真实作答）────────────────────────────────

INSIGHT_SYSTEM_PROMPT = (
    "You analyze spelling-practice results for one Chinese secondary school "
    "student. You receive ONLY anonymized real answer records (word, "
    "meaning, the student's first-try answer, correct spelling). Respond "
    "with ONLY a JSON object (no markdown): "
    '{"summary": "<简体中文总结，不超过150字，基于给定记录>", '
    '"weak_words": ["<只允许从给出的错词列表中选择，原样引用>"], '
    '"suggestions": ["<简体中文可执行复习建议，最多4条，每条不超过60字>"]}. '
    "Never invent records, never mention the student's identity, never "
    "label the student."
)

INSIGHT_WEAK_MAX = 6


def build_session_evidence(
    session: Session, vocab_session: VocabularySession, snapshot_items: list[dict]
) -> tuple[list[dict[str, object]], int, int, list[dict[str, str]]]:
    """单轮真实作答证据：只取首答（attempt_no=1），未答计数。

    返回 (全部题证据, answered, total, 错词证据列表)。
    """
    from app.services.vocabulary import answers_by_item

    grouped = answers_by_item(session, vocab_session.id)
    evidence: list[dict[str, object]] = []
    wrong: list[dict[str, str]] = []
    answered = 0
    for idx, snapshot_item in enumerate(snapshot_items):
        attempts = grouped.get(idx, [])
        first = next((a for a in attempts if a.attempt_no == 1), None)
        meaning = str(snapshot_item["meaning_zh"])
        headword = str(snapshot_item["headword"])
        if first is None:
            evidence.append(
                {"word": headword, "meaning": meaning, "result": "unanswered"}
            )
            continue
        answered += 1
        evidence.append(
            {
                "word": headword,
                "meaning": meaning,
                "result": "correct" if first.is_correct else "wrong",
            }
        )
        if not first.is_correct:
            wrong.append(
                {
                    "headword": headword,
                    "meaning_zh": meaning,
                    "your_answer": first.answer_raw,
                    "correct_spelling": headword,
                }
            )
    return evidence, answered, len(snapshot_items), wrong


def build_insight_user_prompt(
    evidence: list[dict[str, object]], wrong_headwords: list[str]
) -> str:
    return (
        "Real answer records (anonymized):\n"
        + json.dumps(evidence, ensure_ascii=False)
        + "\n\nWrong words you may reference (choose only from these): "
        + json.dumps(wrong_headwords, ensure_ascii=False)
    )


def _validate_insight_payload(
    data: dict,
    wrong_pool: list[dict[str, str]],
    summary_fallback: str,
) -> tuple[str, list[dict[str, str]], list[str]]:
    """模型输出按不可信处理：summary 截断；weak_words 只保留真实错词池
    里存在的（不虚构）；suggestions 截断条数与长度。"""
    summary = _clean_str(data.get("summary"), 400) or summary_fallback
    by_headword = {w["headword"].casefold(): w for w in wrong_pool}
    weak: list[dict[str, str]] = []
    for raw in data.get("weak_words", []) or []:
        name = _clean_str(raw, 64)
        if not name:
            continue
        match = by_headword.get(name.casefold())
        if match is not None and all(w["headword"] != match["headword"] for w in weak):
            weak.append(match)
        if len(weak) >= INSIGHT_WEAK_MAX:
            break
    suggestions = [
        s_
        for s_ in (_clean_str(v, 120) for v in data.get("suggestions", []) or [])
        if s_
    ][:4]
    return summary, weak, suggestions


def session_insight_fingerprint(session: Session, vocab_session_id: uuid.UUID) -> str:
    """单轮指纹：作答条数 + 最大作答 id（新作答即变化）。"""
    answers = session.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == vocab_session_id  # type: ignore[arg-type]
        )
    ).all()
    count = len(answers)
    max_id = max((a.id for a in answers), default=uuid.UUID(int=0))
    return f"{count}:{max_id}"


def generate_session_insight(
    session: Session,
    vocab_session: VocabularySession,
    snapshot_items: list[dict],
) -> dict[str, object]:
    evidence, answered, total, wrong_pool = build_session_evidence(
        session, vocab_session, snapshot_items
    )
    content = _chat(
        system=INSIGHT_SYSTEM_PROMPT,
        user=build_insight_user_prompt(evidence, [w["headword"] for w in wrong_pool]),
        temperature=0.3,
    )
    data = parse_model_json_object(content)
    summary_fallback = (
        f"本轮共 {total} 题，已答 {answered} 题，"
        f"答错 {len(wrong_pool)} 题。建议优先复习上列薄弱词。"
    )
    summary, weak, suggestions = _validate_insight_payload(
        data, wrong_pool, summary_fallback
    )
    return {
        "summary": summary,
        "weak_words": weak,
        "suggestions": suggestions,
        "scope": {
            "answered_count": answered,
            "total_count": total,
        },
    }


def overall_fingerprint(
    session: Session, student_id: uuid.UUID, limit: int, days: int
) -> tuple[str, datetime, datetime, int, int, list[dict[str, str]], int]:
    """整体学情的范围与指纹：最近 limit 轮（有作答）、最近 days 天，
    测验答卷仅在答案公布后计入（不绕过答案可见规则）。

    返回 (指纹, from, to, rounds_used, answered_total, 错词池, 证据最大 id)。
    """
    from app.models import VocabularyAssignment

    cutoff = datetime.now(UTC) - timedelta(days=days)
    answers = session.exec(
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
            col(VocabularyAnswer.answered_at) >= cutoff,  # type: ignore[operator]
            # 答案可见规则：未公布答案的测验作答不进入学情证据
            (col(VocabularySession.assignment_id).is_(None))  # type: ignore[union-attr]
            | (col(VocabularyAssignment.mode) != "quiz")  # type: ignore[operator]
            | col(VocabularyAssignment.answers_published_at).is_not(None),  # type: ignore[union-attr]
        )
        .order_by(col(VocabularyAnswer.answered_at).desc())
    ).all()
    evidence_max_id = max((a.id for a in answers), default=uuid.UUID(int=0))
    # 最近 limit 个「有作答的轮次」：按 session 分组取轮次集合
    seen_sessions: dict[uuid.UUID, int] = {}
    for answer in answers:
        seen_sessions.setdefault(answer.session_id, 0)
        seen_sessions[answer.session_id] += 1
    rounds_used = min(len(seen_sessions), limit) if seen_sessions else 0
    # 只保留最近 limit 轮的作答作为证据
    keep_sessions = set(list(seen_sessions.keys())[:limit])
    scoped = [a for a in answers if a.session_id in keep_sessions]
    wrong_pool: dict[uuid.UUID, dict[str, str]] = {}
    for answer in scoped:
        if answer.attempt_no == 1 and not answer.is_correct:
            wrong_pool.setdefault(
                answer.word_id,
                {
                    "headword": answer.headword,
                    "meaning_zh": answer.meaning_zh,
                    "your_answer": answer.answer_raw,
                    "correct_spelling": answer.headword,
                },
            )
    fingerprint = f"{rounds_used}:{len(scoped)}:{evidence_max_id}"
    times = [a.answered_at for a in scoped if a.answered_at]
    return (
        fingerprint,
        min(times) if times else cutoff,
        max(times) if times else datetime.now(UTC),
        rounds_used,
        len(scoped),
        list(wrong_pool.values()),
        len(scoped),
    )


def generate_overall_insight(
    *,
    scope_meta: dict[str, object],
    wrong_pool: list[dict[str, str]],
    evidence_digest: list[dict[str, object]],
) -> dict[str, object]:
    """生成整体建议；范围口径（limit/days）已折入 scope_meta 与证据摘要。"""
    content = _chat(
        system=INSIGHT_SYSTEM_PROMPT,
        user=build_insight_user_prompt(
            evidence_digest, [w["headword"] for w in wrong_pool]
        ),
        temperature=0.3,
    )
    data = parse_model_json_object(content)
    summary_fallback = (
        f"最近 {scope_meta.get('rounds')} 次练习（{scope_meta.get('days')} 天内）"
        f"共作答 {scope_meta.get('answered_count')} 题，"
        f"拼错 {len(wrong_pool)} 个词。建议按上列薄弱词安排复习。"
    )
    summary, weak, suggestions = _validate_insight_payload(
        data, wrong_pool, summary_fallback
    )
    return {
        "summary": summary,
        "weak_words": weak,
        "suggestions": suggestions,
        "scope": scope_meta,
    }


# ── 缓存读写 ───────────────────────────────────────────────────────


def get_cached_insight(
    session: Session, cache_key: str, fingerprint: str
) -> tuple[dict | None, datetime | None, bool]:
    """返回 (payload, created_at, stale)：指纹一致=新鲜；不一致=旧缓存待更新。"""
    row = session.exec(
        select(VocabularyAiCache).where(
            VocabularyAiCache.cache_key == cache_key  # type: ignore[arg-type]
        )
    ).first()
    if row is None:
        return None, None, False
    return row.payload, row.created_at, row.fingerprint != fingerprint


def save_insight_cache(
    session: Session,
    *,
    cache_key: str,
    kind: str,
    student_id: uuid.UUID | None,
    payload: dict,
    fingerprint: str,
) -> None:
    """写缓存；并发撞唯一键时回滚改更新（去重语义：同一 key 只留一行）。"""
    row = session.exec(
        select(VocabularyAiCache).where(
            VocabularyAiCache.cache_key == cache_key  # type: ignore[arg-type]
        )
    ).first()
    if row is None:
        row = VocabularyAiCache(
            cache_key=cache_key,
            kind=kind,
            student_id=student_id,
            payload=payload,
            fingerprint=fingerprint,
        )
        session.add(row)
        try:
            session.commit()
        except Exception:
            session.rollback()
            row = session.exec(
                select(VocabularyAiCache).where(
                    VocabularyAiCache.cache_key == cache_key  # type: ignore[arg-type]
                )
            ).first()
            if row is None:
                raise
    row.payload = payload
    row.fingerprint = fingerprint
    row.created_at = get_datetime_utc()
    session.add(row)
    session.commit()
