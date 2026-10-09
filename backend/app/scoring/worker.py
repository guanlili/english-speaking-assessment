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

from sqlalchemy import update
from sqlalchemy.orm import load_only
from sqlmodel import Session, col, func, select

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
# 终局关闭标志（返修R07）：置位后池创建与投递在同一把锁内被拒绝——
# 已通过检查、尚未实际 submit 的迟到回调（Timer/清扫/主评分收尾）
# 都不能再重建线程池。测试中途排水用 shutdown_executor(final=False)
_executor_stopped = False
# 在飞重试 Timer 登记：退出时统一取消
_retry_timers: set[threading.Timer] = set()
_retry_timers_lock = threading.Lock()
# 已恢复但投递失败/未确认领取的重投候选：每轮清扫重试，不依赖录音年龄
_resubmit_pending: set[uuid.UUID] = set()
_resubmit_lock = threading.Lock()


class _LeaseLostError(Exception):
    """本线程的领取已被回收或重领：放弃一切写回，不标失败不改状态。"""


def _schedule_retry(attempt_id: uuid.UUID, delay: float) -> None:
    """延迟重投（带登记）：退出时统一取消，避免关闭后重建线程池。"""
    holder: dict[str, threading.Timer] = {}

    def fire() -> None:
        with _retry_timers_lock:
            _retry_timers.discard(holder["timer"])
        # 终局关闭后放弃重投：检查与投递在 executor 锁内与 shutdown 串行化，
        # 不存在「检查已通过、池被关闭又重建」的窗口（返修R07）
        with _executor_lock:
            if _executor_stopped:
                logger.info("scoring executor stopped; drop retry for %s", attempt_id)
                return
        submit_attempt_scoring(attempt_id)

    timer = threading.Timer(delay, fire)
    holder["timer"] = timer
    with _retry_timers_lock:
        _retry_timers.add(timer)
    timer.daemon = True
    timer.start()


def _remember_resubmit(attempt_id: uuid.UUID) -> None:
    with _resubmit_lock:
        _resubmit_pending.add(attempt_id)


def _drain_pending_resubmits(session: Session) -> int:
    """投递失败/未确认领取的重投候选：仍处于 queued 的重新投递。

    候选留在集合里直到观察到它离开 queued（被领取/终结）——若投递被拒
    （线程池关闭等异常）下轮清扫继续重试，恢复不依赖录音创建年龄。
    """
    with _resubmit_lock:
        candidates = list(_resubmit_pending)
    if not candidates:
        return 0
    still_queued = set(
        session.exec(
            select(Attempt.id).where(
                col(Attempt.id).in_(candidates),
                Attempt.status == AttemptStatus.QUEUED,
            )
        ).all()
    )
    submitted = 0
    for row_id in still_queued:
        try:
            submit_attempt_scoring(row_id)
            submitted += 1
        except Exception:  # noqa: BLE001 - 投递失败留在集合，下轮重试
            logger.exception("resubmit dispatch failed for %s", row_id)
    with _resubmit_lock:
        _resubmit_pending.intersection_update(still_queued)
    return submitted


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


# 进程内五级词库缓存：签名 = 过滤集 (count, max(created_at))。
# 词表可发生的变更（导入插入、人工核对、启停用）都会改变过滤集 count，
# 而 headword/level 不可编辑，故签名一致即可复用，无需 updated_at 列。
# 多进程部署时各进程独立校验签名，天然一致。
_five_level_cache_lock = threading.Lock()
_five_level_cache: tuple[tuple[int, datetime | None], dict[str, set[str]]] | None = None


def _get_five_level_cache(session: Session) -> dict[str, set[str]]:
    """五级分级词条缓存（active 且已人工核对）：level → 词头集合。词组不计入逐词命中。

    评分热路径每条词汇作答都会调用，全表约 8k 行；签名命中时直接复用，
    未命中才全量重建（聚合签名查询远轻于拖 8k 行回 Python）。
    """
    global _five_level_cache
    from app.models import VocabularyLevelEntry

    active_filter = (
        VocabularyLevelEntry.status == "active",
        col(VocabularyLevelEntry.is_phrase).is_(False),
        col(VocabularyLevelEntry.needs_review).is_(False),
        col(VocabularyLevelEntry.meaning_zh).is_not(None),
        col(VocabularyLevelEntry.meaning_zh) != "",
    )
    row = session.exec(
        select(func.count(), func.max(VocabularyLevelEntry.created_at)).where(
            *active_filter
        )
    ).one()
    signature = (int(row[0]), row[1])
    cached = _five_level_cache
    if cached is not None and cached[0] == signature:
        return cached[1]
    with _five_level_cache_lock:
        cached = _five_level_cache
        if cached is not None and cached[0] == signature:
            return cached[1]
        levels: dict[str, set[str]] = {}
        for headword, level in session.exec(
            select(VocabularyLevelEntry.headword, VocabularyLevelEntry.level).where(
                *active_filter
            )
        ).all():
            levels.setdefault(level, set()).add(headword)
        _five_level_cache = (signature, levels)
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

    领取租约：以 claimed_at 的领取时刻作为本线程代次标识；checkpoint、
    最终结果与失败回退写回前都在行锁内校验代次仍有效——慢旧 worker 在
    被回收/重领后不能改写新 worker 的结果，只能放弃自己的写回。
    外部 ASR/LLM 调用不持有数据库行锁；崩溃窗口（调用中途被回收）由
    checkpoint + 重试覆盖，不承诺付费调用的严格 exactly-once。
    """
    # 原子领取：FOR UPDATE SKIP LOCKED 防止并发重复评分
    attempt = session.exec(
        select(Attempt)
        .where(Attempt.id == attempt_id, Attempt.status == AttemptStatus.QUEUED)
        .with_for_update(skip_locked=True)
    ).first()
    if attempt is None:
        return  # 已被其他 worker 领取或已处理

    # 租约令牌在写入前局部生成（返修R04）：commit 默认 expire ORM，
    # 之后读 attempt.claimed_at 会触发重新 SELECT——若本线程在提交后停顿
    # 且已被回收重领，会「认领」别人的新令牌。令牌只存在于局部变量
    claim_token = datetime.now(UTC)
    attempt.status = AttemptStatus.SCORING
    attempt.claimed_at = claim_token
    session.add(attempt)
    session.commit()
    lease_token = claim_token

    def lease_valid() -> bool:
        """行锁内裸读领取代次：仍处 scoring 且 claimed_at 是本线程领取值。

        不能用 refresh 校验——refresh 会用库里的旧值覆盖 session 中
        已算出未提交的评分结果；裸列查询（no_autoflush）拿到行锁后，
        本次事务内的写回与校验原子完成。
        """
        with session.no_autoflush:
            row = session.exec(
                select(Attempt.claimed_at, Attempt.status)
                .where(Attempt.id == attempt_id)
                .with_for_update()
            ).first()
        return (
            row is not None
            and row[1] == AttemptStatus.SCORING
            and row[0] == lease_token
        )

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
            if not lease_valid():
                raise _LeaseLostError(attempt_id)
            # checkpoint：转写成功立即落库（同步保存真实 ASR provider），
            # 后续环节失败重试时不再重跑 ASR；同时续租 claimed_at——
            # 阶段推进即心跳，健康慢任务不会被误判成失联僵尸
            attempt.transcript = transcript
            attempt.engine = engine
            renewal = datetime.now(UTC)
            attempt.claimed_at = renewal
            session.add(attempt)
            session.commit()
            lease_token = renewal

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
                # 详情任务入队（返修R06）：queued_at 是排队时刻；真正开始
                # 执行时 _complete_detail 会改写为 executing + pending_since。
                # 挂起超时按阶段判定——合法的线程池排队不该被当线程丢失
                attempt.rubric = {
                    "status": "pending",
                    "phase": "queued",
                    "queued_at": datetime.now(UTC).isoformat(),
                }
                detail_request = (prompt, band, transcript)

        if not lease_valid():
            raise _LeaseLostError(attempt_id)
        attempt.status = AttemptStatus.DONE
        attempt.engine = engine
    except _LeaseLostError:
        # 领取已被回收/重领：本线程结果作废，不写任何状态（新 worker 接管）
        session.rollback()
        logger.warning(
            "attempt %s lease lost before write-back; discarding stale result",
            attempt_id,
        )
        return
    except ContentMissingError as exc:
        # 题目内容已被删除：重试无意义，直接标失败不消耗重试配额
        logger.error(
            "attempt %s scoring aborted (content missing): %s",
            attempt_id,
            exc,
            exc_info=True,
        )
        if not lease_valid():
            return
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
        if not lease_valid():
            return
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
        # 退出中完成的主评分：优雅放弃详情投递（重启后 startup 兜底），
        # 不抛错也不重建已关闭的详情池（返修R07）
        with _executor_lock:
            if _executor_stopped:
                logger.info("executor stopped; skip detail submit for %s", attempt_id)
                return
            detail_executor = _ensure_detail_executor_locked()
        detail_executor.submit(_complete_detail, attempt_id, *detail_request)


def _complete_detail(
    attempt_id: uuid.UUID, prompt: str, band: str, transcript: str
) -> None:
    from app.core.db import engine

    # 执行开始即续期（返修R06）：排队时刻换成执行时刻，清扫的 120 秒
    # 超时从此计——线程池排队再久也不会被误判；已被清扫关闭（非
    # pending）则放弃本次调用，不烧费用
    with Session(engine) as session:
        attempt = session.get(Attempt, attempt_id)
        if attempt is not None and attempt.status == AttemptStatus.DONE:
            session.refresh(attempt, with_for_update=True)
            rubric = attempt.rubric if isinstance(attempt.rubric, dict) else None
            if (
                attempt.status == AttemptStatus.DONE
                and rubric is not None
                and rubric.get("status") == "pending"
            ):
                attempt.rubric = {
                    "status": "pending",
                    "phase": "executing",
                    "pending_since": datetime.now(UTC).isoformat(),
                }
                session.add(attempt)
                session.commit()
            else:
                return

    result = _score_rubric(prompt, band, transcript)
    with Session(engine) as session:
        attempt = session.get(Attempt, attempt_id)
        if attempt is not None and attempt.status == AttemptStatus.DONE:
            # 行锁内确认 rubric 仍处于 pending：先到先得，迟到的旧 detail
            # 线程（重试/回收后重跑产生的重复投递）不得覆盖新结果
            session.refresh(attempt, with_for_update=True)
            rubric = attempt.rubric if isinstance(attempt.rubric, dict) else None
            if (
                attempt.status == AttemptStatus.DONE
                and rubric is not None
                and rubric.get("status") == "pending"
            ):
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
                _schedule_retry(attempt_id, delay)
            else:
                submit_attempt_scoring(attempt_id)


def _ensure_executor_locked() -> ThreadPoolExecutor:
    """在已持有 _executor_lock 的前提下确保主评分池存在（返修R07）。

    终局关闭后拒绝重建：创建、投递与关闭共享同一把锁，「检查通过后
    池被关闭又重建」的窗口不存在。
    """
    global _executor
    if _executor is None:
        if _executor_stopped:
            raise RuntimeError(
                "scoring executor stopped; cannot recreate after final shutdown"
            )
        _executor = ThreadPoolExecutor(
            max_workers=settings.SCORING_WORKERS,
            thread_name_prefix="scoring",
        )
    return _executor


def get_executor() -> ThreadPoolExecutor:
    """获取（必要时创建）主评分线程池。测试中途排水后复用见
    shutdown_executor(final=False)。"""
    if _executor is None:
        with _executor_lock:
            _ensure_executor_locked()
    assert _executor is not None
    return _executor


def _ensure_detail_executor_locked() -> ThreadPoolExecutor:
    global _detail_executor
    if _detail_executor is None:
        if _executor_stopped:
            raise RuntimeError(
                "detail executor stopped; cannot recreate after final shutdown"
            )
        _detail_executor = ThreadPoolExecutor(
            max_workers=settings.SCORING_WORKERS,
            thread_name_prefix="feedback",
        )
    return _detail_executor


def _get_or_create_detail_executor() -> ThreadPoolExecutor:
    if _detail_executor is None:
        with _executor_lock:
            _ensure_detail_executor_locked()
    assert _detail_executor is not None
    return _detail_executor


def submit_attempt_scoring(attempt_id: uuid.UUID) -> None:
    with _executor_lock:
        if _executor_stopped:
            logger.info("scoring executor stopped; skip resubmit for %s", attempt_id)
            return
        executor = _ensure_executor_locked()
    executor.submit(_run_in_worker, attempt_id)


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
    recovered_ids: list[uuid.UUID] = []
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
            recovered_ids.append(attempt.id)
        else:
            attempt.status = AttemptStatus.FAILED
            attempt.error = "评分多次失败（重试上限）"
            session.add(attempt)
            changed = True
    if changed:
        # 只要有状态变更（含超限标 failed）就必须落库，否则僵尸永远卡在 scoring
        session.commit()
        logger.info("recovered %d stale scoring attempts", recovered)
        # 恢复提交成功即投递：不等待「录音创建超过 30 分钟」的孤儿规则——
        # 恢复延迟从半小时量级降到毫秒级；投递被拒时进 pending 集合由
        # 下一轮清扫继续重试（不依赖原录音年龄）
        for attempt_id in recovered_ids:
            _remember_resubmit(attempt_id)
            try:
                submit_attempt_scoring(attempt_id)
            except Exception:  # noqa: BLE001 - 投递失败留在集合，下轮重试
                logger.exception("resubmit after recovery failed for %s", attempt_id)
    return recovered


# 详情任务在队列里的最长等待（返修R06）：排队 30 分钟仍未开始执行，
# 视为线程/任务丢失；正常 backlog（线程数有限）不会触达
DETAIL_QUEUED_STALE_TIMEOUT_S = 30 * 60


def _detail_stale_values(
    rubric: dict[str, object] | None, created_at: datetime | None, now: datetime
) -> bool:
    """详情挂起超时判定（值语义，供 ORM 快照与行锁重读共用）。

    - phase=queued：按 queued_at，超过 30 分钟才视为任务丢失——线程池
      正常排队（40 份任务 × 慢调用）不误判（返修R06）；
    - phase=executing（或历史行无 phase）：按 pending_since（缺失回落
      created_at）判 120 秒——真正开始过的调用超时即失联；
    """
    if rubric is None or rubric.get("status") != "pending":
        return False

    def _parse(value: object) -> datetime | None:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    if rubric.get("phase") == "queued":
        base = _parse(rubric.get("queued_at")) or created_at
        timeout = DETAIL_QUEUED_STALE_TIMEOUT_S
    else:
        base = _parse(rubric.get("pending_since")) or created_at
        timeout = SCORING_STALE_TIMEOUT_S
    if base is None:
        return True
    return now - base > timedelta(seconds=timeout)


def _detail_stale(attempt: Attempt, now: datetime) -> bool:
    """详情阶段挂起超时判定（ORM 便捷封装）。"""
    rubric = attempt.rubric if isinstance(attempt.rubric, dict) else None
    return _detail_stale_values(rubric, attempt.created_at, now)


def sweep_orphans(session: Session) -> int:
    """运行期兜底清理（进程不重启也能自愈）：

    - 僵尸 SCORING 恢复（线程在 LLM 调用中被杀/会话提交中断等）；
    - 孤儿 QUEUED 重投： QUEUED 超过 QUEUED_STALE_TIMEOUT_S 仍无 worker 领取
      （线程池 future 丢失等），避免僵尸永久占坑——队列容量按 QUEUED 计数，
      占满 200 条后全站上传 503。重投幂等：领取走 SKIP LOCKED + 状态门，
      对已在执行中的作答二次投递是无害空转；
    - 恢复候选补投：恢复后投递失败/未确认领取的作答，每轮重试直到
      离开 queued（不依赖录音创建年龄）；
    - 悬置 rubric 关闭： detail 线程丢失导致 DONE 但 rubric 停在 pending
      （按详情阶段开始时刻判定挂起，详见 _detail_stale）。

    返回重投的 QUEUED 作答数。
    """
    recover_stale_attempts(session)
    resubmitted = _drain_pending_resubmits(session)
    now = datetime.now(UTC)
    for attempt_id, created_at in session.exec(
        select(Attempt.id, Attempt.created_at).where(
            Attempt.status == AttemptStatus.QUEUED
        )
    ).all():
        created = created_at.timestamp() if created_at is not None else 0
        if now.timestamp() - created >= QUEUED_STALE_TIMEOUT_S:
            submit_attempt_scoring(attempt_id)
            resubmitted += 1
    stale_cutoff = datetime.now(UTC) - timedelta(seconds=SCORING_STALE_TIMEOUT_S)
    # load_only 只取 rubric/created_at；SQL 层直接筛「rubric 处于 pending」
    # （rubric->>'status'）：DONE 量随学期累积，绝大多数历史行 rubric 为
    # null/已关闭，不该每 60s 拉回 Python 再丢掉。索引不盲加——候选集经
    # status+created_at 前缀过滤后已足够小，是否需要 JSON 表达式索引由
    # perf_baseline 实测 EXPLAIN 决定
    pending = session.exec(
        select(Attempt)
        .options(
            load_only(
                Attempt.id,  # ty: ignore[invalid-argument-type]
                Attempt.rubric,  # ty: ignore[invalid-argument-type]
                Attempt.created_at,  # ty: ignore[invalid-argument-type]
            )
        )
        .where(
            Attempt.status == AttemptStatus.DONE,
            col(Attempt.created_at) < stale_cutoff,  # type: ignore[operator]
            col(Attempt.rubric)["status"].as_string() == "pending",  # type: ignore[index]
        )
    ).all()
    check_now = datetime.now(UTC)
    closed = 0
    for attempt in pending:
        if not _detail_stale(attempt, check_now):
            continue
        # 行锁内重读并按最新值复判（返修R05）：候选快照之后详情线程可能
        # 已把 pending 续期为 executing 或写回成功结果——陈旧快照不得
        # 覆盖，条件 UPDATE 只关「此刻仍为本轮判定的 pending」
        locked = session.exec(
            select(Attempt.id, Attempt.rubric, Attempt.created_at)
            .where(Attempt.id == attempt.id)
            .with_for_update()
        ).first()
        if locked is None:
            continue
        fresh_rubric = locked[1] if isinstance(locked[1], dict) else None
        if fresh_rubric is None or fresh_rubric.get("status") != "pending":
            continue
        if not _detail_stale_values(fresh_rubric, locked[2], datetime.now(UTC)):
            continue
        session.execute(  # ty: ignore[deprecated] - exec() 不接受 update 语句
            update(Attempt)
            .where(col(Attempt.id) == attempt.id)
            .values(rubric={"status": "unavailable"})
        )
        closed += 1
    if closed:
        logger.info("detail sweep closed %d stale rubrics", closed)
    session.commit()
    return resubmitted


def startup_recovery() -> None:
    """进程启动时恢复僵尸 scoring 作答并重新提交评分。"""
    from app.core.db import engine

    with Session(engine) as session:
        # 同 sweep_orphans：SQL 层筛「rubric 处于 pending」+ load_only 窄列，
        # 启动不把整个学期的 DONE 行拉回 Python；挂起按详情阶段开始时刻
        # 判定（详见 _detail_stale）
        check_now = datetime.now(UTC)
        for attempt in session.exec(
            select(Attempt)
            .options(
                load_only(
                    Attempt.id,  # ty: ignore[invalid-argument-type]
                    Attempt.rubric,  # ty: ignore[invalid-argument-type]
                    Attempt.created_at,  # ty: ignore[invalid-argument-type]
                )
            )
            .where(
                Attempt.status == AttemptStatus.DONE,
                col(Attempt.rubric)["status"].as_string() == "pending",  # type: ignore[index]
            )
        ).all():
            if not _detail_stale(attempt, check_now):
                continue
            # 行锁重读复判（返修R05）：陈旧快照不得覆盖执行中/已完成的详情
            locked = session.exec(
                select(Attempt.id, Attempt.rubric, Attempt.created_at)
                .where(Attempt.id == attempt.id)
                .with_for_update()
            ).first()
            if locked is None:
                continue
            fresh_rubric = locked[1] if isinstance(locked[1], dict) else None
            if fresh_rubric is None or fresh_rubric.get("status") != "pending":
                continue
            if not _detail_stale_values(fresh_rubric, locked[2], datetime.now(UTC)):
                continue
            session.execute(  # ty: ignore[deprecated] - exec() 不接受 update 语句
                update(Attempt)
                .where(col(Attempt.id) == attempt.id)
                .values(rubric={"status": "unavailable"})
            )
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
        # 启动即全量重投，进程内的恢复候选簿记一并清空
        with _resubmit_lock:
            _resubmit_pending.clear()


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


def reset_executors_for_restart() -> None:
    """新生命周期启动时复位终局关闭标志（返修R07 收口）。

    生产每次启动都是新进程（标志天然为 False）；测试进程内多个模块
    共用 app，模块级 client 夹具反复进出 lifespan——上一轮 shutdown
    的 final 标志必须复位，否则后续模块的真实投递被静默跳过。
    """
    global _executor_stopped
    with _executor_lock:
        _executor_stopped = False


def shutdown_executor(final: bool = True) -> None:
    """关闭线程池。final=True 为终局关闭（进程退出/lifespan 结束）：

    置 stopping 标志后迟到回调（Timer/清扫/主评分收尾）在同一把锁内
    被拒绝，不能重建线程池（返修R07）。final=False 仅排水（测试中途
    清理），之后仍可按需重建。
    """
    global _executor, _detail_executor, _executor_stopped
    with _executor_lock:
        if final:
            _executor_stopped = True
        # 取消在飞重试 Timer：fire 回调在锁内看到 stopped 会直接放弃
        with _retry_timers_lock:
            timers = list(_retry_timers)
            _retry_timers.clear()
        for timer in timers:
            timer.cancel()
        if _detail_executor is not None:
            _detail_executor.shutdown(wait=False)
            _detail_executor = None
        if _executor is not None:
            _executor.shutdown(wait=False)
            _executor = None
