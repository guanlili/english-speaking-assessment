"""评分 worker：从队列取作答 → 转写 → 按题型打分 → 写回数据库。

PRD 不可协商 #4：上传接口立即返回，评分在线程池里异步完成。
引擎通过 settings.SCORING_PROVIDER 切换（mock / ark），
不暴露成请求参数，避免演示时被切到贵的引擎（PRD 附录 A）。
"""

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    MAX_SCORING_RETRIES,
    QUEUED_STALE_TIMEOUT_S,
    SCORING_STALE_TIMEOUT_S,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Passage,
    RepeatSentence,
    ScenarioQuestion,
)
from app.scoring.asr import ArkResponsesAsr, MockAsr
from app.scoring.audio_convert import convert_to_wav, ensure_ark_supported
from app.scoring.base import AsrProvider, ContentMissingError, ScoringError
from app.scoring.heuristic import score_open_response, score_read_aloud
from app.scoring.volc_flash import VolcFlashAsr

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_detail_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


_TOKEN_RE = re.compile(r"[a-z']+")
_CONSONANTS = set("bcdfghjklmnpqrstvwxyz")


def _lemma_variants(token: str) -> list[str]:
    """轻量词元归一：处理规则屈折（复数/进行时/过去式），不规则形式由词表直接收录。"""
    variants = [token]
    if token.endswith("ies") and len(token) > 4:
        variants.append(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        variants.append(token[:-2])
    if token.endswith("s") and len(token) > 2:
        variants.append(token[:-1])
    if token.endswith("ing") and len(token) > 5:
        stem = token[:-3]
        variants.append(stem)
        variants.append(stem + "e")  # making → make
        if (
            len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] in _CONSONANTS
        ):  # running → run
            variants.append(stem[:-1])
    if token.endswith("ed") and len(token) > 4:
        stem = token[:-2]
        variants.append(stem)
        variants.append(token[:-1])  # hoped → hope
        if (
            len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] in _CONSONANTS
        ):  # stopped → stop
            variants.append(stem[:-1])
    if token.endswith("er") and len(token) > 4:
        variants.append(token[:-2])
        variants.append(token[:-1])
    if token.endswith("est") and len(token) > 5:
        variants.append(token[:-3])
        variants.append(token[:-2])
    return list(dict.fromkeys(variants))


def _get_five_level_cache(session: Session) -> dict[str, set[str]]:
    """五级分级词条缓存（active 且已人工核对）：level → 词头集合。词组不计入逐词命中。"""
    from app.models import VocabularyLevelEntry

    levels: dict[str, set[str]] = {}
    for headword, level in session.exec(
        select(VocabularyLevelEntry.headword, VocabularyLevelEntry.level).where(
            VocabularyLevelEntry.status == "active",
            VocabularyLevelEntry.is_phrase.is_(False),  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            VocabularyLevelEntry.needs_review.is_(False),  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            VocabularyLevelEntry.meaning_zh.is_not(None),  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
            VocabularyLevelEntry.meaning_zh != "",  # type: ignore[union-attr]
        )
    ).all():
        levels.setdefault(level, set()).add(headword)
    return levels


def _five_level_stats(session: Session, transcript: str) -> dict[str, object] | None:
    """用词来源级别统计（与 A2/B1/B2 分析同一段转写、彼此独立）。

    只陈述「实际用到的词来自哪些级别」（按五级固定顺序取最易一级归类），
    不代表学生能力等级。五级数据未导入时返回 None（界面不显示该块）。
    """
    levels = _get_five_level_cache(session)
    if not any(levels.values()):
        return None
    tokens = set(_TOKEN_RE.findall(transcript.lower()))
    if not tokens:
        return None
    from app.models import VOCAB_LEVEL_ORDER

    hits_by_level: dict[str, int] = {}
    unmatched = 0
    for token in sorted(tokens):
        hit_levels = [
            level
            for level in VOCAB_LEVEL_ORDER
            if any(
                variant in levels.get(level, set())
                for variant in _lemma_variants(token)
            )
        ]
        if not hit_levels:
            unmatched += 1
            continue
        effective = min(hit_levels, key=VOCAB_LEVEL_ORDER.index)
        hits_by_level[effective] = hits_by_level.get(effective, 0) + 1
    return {
        "hits_by_level": hits_by_level,
        "unmatched": unmatched,
        "distinct_words": len(tokens),
    }


def _analyze_vocab(session: Session, transcript: str) -> dict[str, object] | None:
    """词汇分析（2026-10 起：五级词库唯一口径）。

    - 只产出五级「用词来源级别」统计（level_stats）；老 A2/B1/B2 词表口径
      已退役，仅历史 attempt.vocab 中的旧 JSON 原样保留展示（不回填不重算）；
    - 五级数据未导入时返回 None（界面显示「分级词库未导入」），作答与
      判分完全不受影响。
    """
    level_stats = _five_level_stats(session, transcript)
    if level_stats is None:
        return None
    return {"level_stats": level_stats}


def build_asr_provider() -> AsrProvider:
    if settings.SCORING_PROVIDER == "ark":
        if settings.ASR_PROVIDER == "volc_flash":
            return VolcFlashAsr(api_key=settings.VOLC_ASR_API_KEY or "")
        if not settings.ARK_API_KEY:
            raise ScoringError("SCORING_PROVIDER=ark 但未配置 ARK_API_KEY")
        return ArkResponsesAsr(
            api_key=settings.ARK_API_KEY,
            model=settings.ARK_ASR_MODEL,
            base_url=settings.ARK_BASE_URL,
        )
    return MockAsr()


def _resolve_read_aloud_item(
    session: Session, attempt: Attempt
) -> tuple[str, int] | None:
    """返回 (参考文本, 建议秒数)；题型不是跟读类时返回 None。"""
    if isinstance(attempt.item_snapshot, dict):
        if attempt.item_type not in (AttemptItemType.PASSAGE, AttemptItemType.REPEAT):
            return None
        text = attempt.item_snapshot.get("text")
        if isinstance(text, str) and text.strip():
            suggested = attempt.item_snapshot.get("suggested_seconds", 20)
            return text, int(suggested) if isinstance(suggested, (int, float)) else 20
    if attempt.item_type == AttemptItemType.PASSAGE:
        passage = session.get(Passage, attempt.item_id)
        if passage is None:
            raise ContentMissingError("篇目不存在")
        return passage.text, passage.suggested_seconds
    if attempt.item_type == AttemptItemType.REPEAT:
        sentence = session.get(RepeatSentence, attempt.item_id)
        if sentence is None:
            raise ContentMissingError("复述句不存在")
        return sentence.text, sentence.suggested_seconds
    return None


def _resolve_question_prompt(session: Session, attempt: Attempt) -> tuple[str, str]:
    if isinstance(attempt.item_snapshot, dict):
        text = attempt.item_snapshot.get("text")
        band = attempt.item_snapshot.get("band", "B1")
        if isinstance(text, str) and text.strip():
            return text, band if isinstance(band, str) else "B1"
    question = session.get(ScenarioQuestion, attempt.item_id)
    if question is None:
        raise ContentMissingError("问题不存在")
    return question.text, question.band


def _score_rubric(prompt: str, band: str, transcript: str) -> dict[str, object] | None:
    """ark 引擎下按 rubric 出四维分 + 0-9 模拟分；失败返回 None（显示暂缺）。"""
    from app.scoring.rubric import ArkRubricScorer

    try:
        scorer = ArkRubricScorer(
            api_key=settings.ARK_API_KEY or "",
            model=settings.ARK_RUBRIC_MODEL,
        )
        scores = scorer.score(prompt, band, transcript)
        return {
            "fluency": scores.fluency,
            "vocabulary": scores.vocabulary,
            "grammar": scores.grammar,
            "task": scores.task,
            "mock_score": scores.mock_score,
            "upgrades": scores.upgrades,
            "advice": scores.advice,
        }
    except Exception as exc:  # noqa: BLE001 - rubric 失败不影响作答本体
        # ERROR 级：Sentry 默认只把 ERROR 转成事件，WARNING 只进 breadcrumb——
        # 评分降级是需要在面板上看见的事
        logger.error("rubric scoring failed: %s", exc, exc_info=True)
        return None


def process_attempt(session: Session, attempt_id: uuid.UUID) -> None:
    """同步评分一条作答。可在线程池中调用，也可在测试中直接调用。

    使用 SELECT FOR UPDATE SKIP LOCKED 原子领取，防止多 worker 重复评分。
    评分失败时按 retry_count 重试，超限后标记 failed。
    """
    # 原子领取：FOR UPDATE SKIP LOCKED 防止并发重复评分
    attempt = session.exec(
        select(Attempt)
        .where(Attempt.id == attempt_id, Attempt.status == AttemptStatus.QUEUED)
        .with_for_update(skip_locked=True)
    ).first()
    if attempt is None:
        return  # 已被其他 worker 领取或已处理

    attempt.status = AttemptStatus.SCORING
    attempt.claimed_at = datetime.now(UTC)
    session.add(attempt)
    session.commit()

    detail_request: tuple[str, str, str] | None = None
    try:
        # ASR 断点：上一轮已转写成功（transcript 已落库）时直接复用，
        # 不再重跑 ASR——重试烧掉的是真实 API 费用，转写结果与音频内容无关可安全复用
        if attempt.transcript is not None:
            transcript = attempt.transcript
            engine = attempt.engine or settings.SCORING_PROVIDER
            logger.info("ASR attempt=%s reused cached transcript", attempt_id)
        else:
            audio_path = Path(attempt.audio_path)
            audio = audio_path.read_bytes()
            provider = build_asr_provider()
            # 方舟不接受浏览器 webm/opus：转 16kHz wav 再送（本地 mock 原样）
            conversion_start = perf_counter()
            if provider.name == "volc_flash":
                audio, effective_mime = convert_to_wav(audio, ".audio")
            elif provider.name == "ark":
                audio, effective_mime = ensure_ark_supported(audio, attempt.audio_mime)
            else:
                effective_mime = attempt.audio_mime
            conversion_ms = (perf_counter() - conversion_start) * 1000
            asr_start = perf_counter()
            transcript = provider.transcribe(audio, effective_mime)
            logger.info(
                "ASR attempt=%s provider=%s conversion_ms=%.0f recognition_ms=%.0f",
                attempt_id,
                provider.name,
                conversion_ms,
                (perf_counter() - asr_start) * 1000,
            )
            engine = provider.name
            # checkpoint：转写成功立即落库，后续环节失败重试时不再重跑 ASR
            attempt.transcript = transcript
            session.add(attempt)
            session.commit()

        read_aloud = _resolve_read_aloud_item(session, attempt)
        if read_aloud is not None:
            reference_text, suggested_seconds = read_aloud
            scores = score_read_aloud(
                transcript=transcript,
                reference_text=reference_text,
                duration_s=attempt.duration_s,
                suggested_seconds=suggested_seconds,
            )
            attempt.transcript = scores.transcript
            attempt.completeness = scores.completeness
            attempt.fluency = scores.fluency
            attempt.accuracy = scores.accuracy
            attempt.overall = scores.overall
            attempt.advice = scores.advice
        else:
            # 开放问答：无参考文本（PRD §4：2 周只出总评和一句建议）
            prompt, band = _resolve_question_prompt(session, attempt)
            open_scores = score_open_response(transcript, attempt.duration_s)
            attempt.transcript = open_scores.transcript
            attempt.fluency = open_scores.fluency
            attempt.overall = open_scores.overall
            attempt.advice = open_scores.advice
            # 词汇分析（PRD US-07）：只统计问答转写；词表为空时留 null
            attempt.vocab = _analyze_vocab(session, transcript)
            # rubric 四维与模拟分（PRD US-08）：仅 ark 引擎；失败降级不出假分
            # 空转写（没说话/识别不到）不出 0 分模拟——界面显示暂缺
            if engine in {"ark", "volc_flash"} and transcript.strip():
                attempt.rubric = {"status": "pending"}
                detail_request = (prompt, band, transcript)

        attempt.status = AttemptStatus.DONE
        attempt.engine = engine
    except ContentMissingError as exc:
        # 题目内容已被删除：重试无意义，直接标失败不消耗重试配额
        logger.error(
            "attempt %s scoring aborted (content missing): %s",
            attempt_id,
            exc,
            exc_info=True,
        )
        attempt.status = AttemptStatus.FAILED
        # 学生端可见的 error 只放通用文案；上游异常原文（可能含 endpoint/配额等细节）只进日志
        attempt.error = "题目内容已不可用，请联系老师重新发布"
    except Exception as exc:  # noqa: BLE001 - 其他引擎异常都按重试/失败处理
        logger.error(
            "attempt %s scoring failed (retry %d): %s",
            attempt_id,
            attempt.retry_count,
            exc,
            exc_info=True,
        )
        if attempt.retry_count < MAX_SCORING_RETRIES:
            attempt.retry_count += 1
            attempt.status = AttemptStatus.QUEUED
            attempt.claimed_at = None
            attempt.error = "评分服务暂时不可用，正在自动重试"
        else:
            attempt.status = AttemptStatus.FAILED
            attempt.error = "评分服务暂时不可用，请稍后重试或联系老师"
    session.add(attempt)
    session.commit()

    if detail_request is not None and attempt.status == AttemptStatus.DONE:
        _detail_executor = _get_or_create_detail_executor()
        _detail_executor.submit(_complete_detail, attempt_id, *detail_request)


def _complete_detail(
    attempt_id: uuid.UUID, prompt: str, band: str, transcript: str
) -> None:
    from app.core.db import engine

    result = _score_rubric(prompt, band, transcript)
    with Session(engine) as session:
        attempt = session.get(Attempt, attempt_id)
        if attempt is not None and attempt.status == AttemptStatus.DONE:
            attempt.rubric = result or {"status": "unavailable"}
            session.add(attempt)
            session.commit()


def _run_in_worker(attempt_id: uuid.UUID) -> None:
    # 延迟导入避免与 app.api.deps 的导入环
    from app.core.db import engine

    with Session(engine) as session:
        process_attempt(session, attempt_id)
        # 失败重排队后必须重新投递，否则作答会永久卡在 queued
        # （retry_count 上限兜底，不会无限循环；测试直接调 process_attempt 不走这里）
        attempt = session.get(Attempt, attempt_id)
        if attempt is not None and attempt.status == AttemptStatus.QUEUED:
            # 退避：引擎抖动通常是几十秒级，立即重投会把重试配额烧在同一个故障窗口里。
            # 放投递层而非 process_attempt：直调 process_attempt 的测试/维护路径不受影响
            delay = min(
                settings.SCORING_RETRY_BACKOFF_S * 2 ** (attempt.retry_count - 1), 60
            )
            if delay > 0:
                timer = threading.Timer(
                    delay, submit_attempt_scoring, args=(attempt_id,)
                )
                timer.daemon = True
                timer.start()
            else:
                submit_attempt_scoring(attempt_id)


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=settings.SCORING_WORKERS,
                    thread_name_prefix="scoring",
                )
    return _executor


def _get_or_create_detail_executor() -> ThreadPoolExecutor:
    global _detail_executor
    if _detail_executor is None:
        with _executor_lock:
            if _detail_executor is None:
                _detail_executor = ThreadPoolExecutor(
                    max_workers=settings.SCORING_WORKERS,
                    thread_name_prefix="feedback",
                )
    return _detail_executor


def submit_attempt_scoring(attempt_id: uuid.UUID) -> None:
    get_executor().submit(_run_in_worker, attempt_id)


def recover_stale_attempts(session: Session) -> int:
    """恢复僵尸 scoring 作答：进程崩溃后遗留的 scoring 状态作答。

    超过 SCORING_STALE_TIMEOUT_S 的 scoring 作答：
    - retry_count 未超限 → 回退为 queued，重新提交评分
    - retry_count 超限 → 标记为 failed

    恢复不消耗 retry_count：僵尸是进程级事件（部署重启/OOM），不是作答本身
    的问题——旧逻辑每次重启烧一次配额，连续两次部署期间在评的作答会被
    直接推成 FAILED 给学生看。

    返回恢复的作答数。
    """
    cutoff = datetime.now(UTC).timestamp() - SCORING_STALE_TIMEOUT_S
    stale = session.exec(
        select(Attempt)
        .where(Attempt.status == AttemptStatus.SCORING)
        .with_for_update(skip_locked=True)
    ).all()
    recovered = 0
    changed = False
    for attempt in stale:
        if attempt.claimed_at is None:
            continue
        if attempt.claimed_at.timestamp() > cutoff:
            continue  # 还在正常评分中
        if attempt.retry_count < MAX_SCORING_RETRIES:
            attempt.status = AttemptStatus.QUEUED
            attempt.claimed_at = None
            attempt.error = "worker 崩溃后自动重试"
            session.add(attempt)
            recovered += 1
            changed = True
        else:
            attempt.status = AttemptStatus.FAILED
            attempt.error = "评分多次失败（重试上限）"
            session.add(attempt)
            changed = True
    if changed:
        # 只要有状态变更（含超限标 failed）就必须落库，否则僵尸永远卡在 scoring
        session.commit()
        logger.info("recovered %d stale scoring attempts", recovered)
    return recovered


def sweep_orphans(session: Session) -> int:
    """运行期兜底清理（进程不重启也能自愈）：

    - 僵尸 SCORING 恢复（线程在 LLM 调用中被杀/会话提交中断等）；
    - 孤儿 QUEUED 重投： QUEUED 超过 QUEUED_STALE_TIMEOUT_S 仍无 worker 领取
      （线程池 future 丢失等），避免僵尸永久占坑——队列容量按 QUEUED 计数，
      占满 200 条后全站上传 503。重投幂等：领取走 SKIP LOCKED + 状态门，
      对已在执行中的作答二次投递是无害空转；
    - 悬置 rubric 关闭： detail 线程丢失导致 DONE 但 rubric 停在 pending。

    返回重投的 QUEUED 作答数。
    """
    recover_stale_attempts(session)
    now = datetime.now(UTC).timestamp()
    resubmitted = 0
    for attempt_id, created_at in session.exec(
        select(Attempt.id, Attempt.created_at).where(
            Attempt.status == AttemptStatus.QUEUED
        )
    ).all():
        created = created_at.timestamp() if created_at is not None else 0
        if now - created >= QUEUED_STALE_TIMEOUT_S:
            submit_attempt_scoring(attempt_id)
            resubmitted += 1
    stale_cutoff = datetime.now(UTC) - timedelta(seconds=SCORING_STALE_TIMEOUT_S)
    pending = session.exec(
        select(Attempt).where(
            Attempt.status == AttemptStatus.DONE,
            col(Attempt.created_at) < stale_cutoff,  # type: ignore[operator]
        )
    ).all()
    for attempt in pending:
        if attempt.rubric and attempt.rubric.get("status") == "pending":
            attempt.rubric = {"status": "unavailable"}
            session.add(attempt)
    session.commit()
    return resubmitted


def startup_recovery() -> None:
    """进程启动时恢复僵尸 scoring 作答并重新提交评分。"""
    from app.core.db import engine

    with Session(engine) as session:
        for attempt in session.exec(
            select(Attempt).where(Attempt.status == AttemptStatus.DONE)
        ).all():
            if attempt.rubric and attempt.rubric.get("status") == "pending":
                attempt.rubric = {"status": "unavailable"}
                session.add(attempt)
        session.commit()
        recover_stale_attempts(session)
        # 无条件重投所有 QUEUED：旧逻辑只在存在僵尸 SCORING 时才重投，会漏掉
        # 「作答落库后、线程领取前进程崩溃」的情况——这些作答重启后无人再投，
        # 永久卡在 queued 占坑，攒满队列上限后全站上传 503。
        # 重投幂等（领取走 SKIP LOCKED + 状态门），多投无害
        for attempt_id in session.exec(
            select(Attempt.id).where(Attempt.status == AttemptStatus.QUEUED)
        ).all():
            submit_attempt_scoring(attempt_id)


SWEEP_INTERVAL_S = 60
_sweeper_stop: threading.Event | None = None
_sweeper_thread: threading.Thread | None = None


def _sweep_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(SWEEP_INTERVAL_S):
        # 引擎每轮重新解析：测试用 set_engine/monkeypatch 覆盖后，清扫也跟着指向目标库
        from app.core.db import engine

        try:
            with Session(engine) as session:
                sweep_orphans(session)
        except Exception:  # noqa: BLE001 - 清扫是兜底，失败只记日志不能带崩线程
            logger.exception("scoring sweeper iteration failed")


def start_sweeper() -> None:
    """启动运行期清扫线程（main lifespan 调用；TestClient 不进 lifespan 故测试不受影响）。"""
    global _sweeper_stop, _sweeper_thread
    if _sweeper_thread is not None and _sweeper_thread.is_alive():
        return
    _sweeper_stop = threading.Event()
    _sweeper_thread = threading.Thread(
        target=_sweep_loop, args=(_sweeper_stop,), name="scoring-sweeper", daemon=True
    )
    _sweeper_thread.start()


def stop_sweeper() -> None:
    global _sweeper_stop, _sweeper_thread
    if _sweeper_stop is not None:
        _sweeper_stop.set()
    _sweeper_stop = None
    _sweeper_thread = None


def shutdown_executor() -> None:
    global _executor, _detail_executor
    if _detail_executor is not None:
        _detail_executor.shutdown(wait=False)
        _detail_executor = None
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
