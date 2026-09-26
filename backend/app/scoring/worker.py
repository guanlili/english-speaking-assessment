"""评分 worker：从队列取作答 → 转写 → 按题型打分 → 写回数据库。

PRD 不可协商 #4：上传接口立即返回，评分在线程池里异步完成。
引擎通过 settings.SCORING_PROVIDER 切换（mock / ark），
不暴露成请求参数，避免演示时被切到贵的引擎（PRD 附录 A）。
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Passage,
    RepeatSentence,
    ScenarioQuestion,
    WordlistEntry,
)
from app.scoring.asr import ArkResponsesAsr, MockAsr
from app.scoring.audio_convert import ensure_ark_supported
from app.scoring.base import AsrProvider, ScoringError
from app.scoring.heuristic import score_open_response, score_read_aloud
from app.scoring.lexicon import analyze_transcript

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def build_asr_provider() -> AsrProvider:
    if settings.SCORING_PROVIDER == "ark":
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
    if attempt.item_type == AttemptItemType.PASSAGE:
        passage = session.get(Passage, attempt.item_id)
        if passage is None:
            raise ScoringError("篇目不存在")
        return passage.text, passage.suggested_seconds
    if attempt.item_type == AttemptItemType.REPEAT:
        sentence = session.get(RepeatSentence, attempt.item_id)
        if sentence is None:
            raise ScoringError("复述句不存在")
        return sentence.text, sentence.suggested_seconds
    return None


def _resolve_question_prompt(session: Session, attempt: Attempt) -> tuple[str, str]:
    question = session.get(ScenarioQuestion, attempt.item_id)
    if question is None:
        raise ScoringError("问题不存在")
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
        }
    except Exception as exc:  # noqa: BLE001 - rubric 失败不影响作答本体
        logger.warning("rubric scoring failed: %s", exc)
        return None


def _analyze_vocab(session: Session, transcript: str) -> dict[str, object] | None:
    """词表命中分析；未配置词表时返回 None（界面显示「未配置词表」，BDD D）。"""
    entries = session.exec(select(WordlistEntry)).all()
    if not entries:
        return None
    lemmas_by_band: dict[str, set[str]] = {"A2": set(), "B1": set(), "B2": set()}
    for entry in entries:
        lemmas_by_band.setdefault(entry.band, set()).add(entry.lemma)
    analysis = analyze_transcript(transcript, lemmas_by_band)
    from app.core.db import WORDLIST_NAME

    return {
        "wordlist": WORDLIST_NAME,
        "hits": {band: words for band, words in analysis.hits_by_band.items() if words},
        "coverage": analysis.coverage_ratio,
        "cefr": analysis.cefr_label,
    }


def process_attempt(session: Session, attempt_id: uuid.UUID) -> None:
    """同步评分一条作答。可在线程池中调用，也可在测试中直接调用。"""
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.status != AttemptStatus.QUEUED:
        return

    attempt.status = AttemptStatus.SCORING
    session.add(attempt)
    session.commit()

    try:
        audio_path = Path(attempt.audio_path)
        audio = audio_path.read_bytes()
        provider = build_asr_provider()
        # 方舟不接受浏览器 webm/opus：转 16kHz wav 再送（本地 mock 原样）
        if provider.name == "ark":
            audio, effective_mime = ensure_ark_supported(audio, attempt.audio_mime)
        else:
            effective_mime = attempt.audio_mime
        transcript = provider.transcribe(audio, effective_mime)
        engine = provider.name

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
            if engine == "ark" and transcript.strip():
                attempt.rubric = _score_rubric(prompt, band, transcript)

        attempt.status = AttemptStatus.DONE
        attempt.engine = engine
    except Exception as exc:  # noqa: BLE001 - 任何引擎异常都落为 failed，音频保留
        logger.warning("attempt %s scoring failed: %s", attempt_id, exc)
        attempt.status = AttemptStatus.FAILED
        attempt.error = str(exc)[:500]
    session.add(attempt)
    session.commit()


def _run_in_worker(attempt_id: uuid.UUID) -> None:
    # 延迟导入避免与 app.api.deps 的导入环
    from app.core.db import engine

    with Session(engine) as session:
        process_attempt(session, attempt_id)


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.SCORING_WORKERS, thread_name_prefix="scoring"
        )
    return _executor


def submit_attempt_scoring(attempt_id: uuid.UUID) -> None:
    get_executor().submit(_run_in_worker, attempt_id)


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None
