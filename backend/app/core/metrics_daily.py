"""大盘日快照：业务量回算 + 运行时峰值采样，每日一行落 admin_metrics_daily。

解决 /admin/metrics 两件事：进程计数器重启归零、没有历史。业务量（作答/
活跃/会话/ASR 秒数）当日从明细表精确回算；运行时峰值（最老排队年龄、
连接池水位、引擎失败数）由本线程 60s 采样在内存里记最大值，跨日时写回。

线程每天跨日（PRACTICE_TZ）落一行昨日快照；启动时回填缺失的历史行
（只回算业务量，峰值为 null——重启前的峰值无法追溯）。
"""

import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlmodel import Session, col

from app.core.config import settings
from app.models import AdminMetricsDaily, Attempt, AttemptStatus, PracticeSession

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_S = 60
BACKFILL_MAX_DAYS = 400


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def compute_daily_business(session: Session, day: date) -> dict[str, object]:
    """按练习日回算业务量（与大盘 P0 同口径：PRACTICE_TZ 切日）。"""
    day_expr = func.date(func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at)))
    a = (
        session.connection()
        .execute(
            select(
                func.count().label("attempts"),
                func.count()
                .filter(col(Attempt.status) == AttemptStatus.DONE)
                .label("done"),
                func.count()
                .filter(col(Attempt.status) == AttemptStatus.FAILED)
                .label("failed"),
                func.count(func.distinct(Attempt.student_id)).label("active"),
                func.coalesce(func.sum(Attempt.duration_s), 0.0).label("seconds"),
            ).where(day_expr == day)
        )
        .one()
    )
    sessions = (
        session.connection()
        .execute(
            select(func.count())
            .select_from(PracticeSession)
            .where(col(PracticeSession.session_date) == day)
        )
        .scalar_one()
    )
    return {
        "attempts": a.attempts,
        "attempts_done": a.done,
        "attempts_failed": a.failed,
        "active_students": a.active,
        "sessions": sessions,
        "asr_seconds": round(float(a.seconds), 1),
    }


def upsert_daily_snapshot(
    session: Session,
    day: date,
    *,
    business: dict[str, object] | None = None,
    llm_calls_by_kind: dict[str, int] | None = None,
    provider_failures: dict[str, int] | None = None,
    llm_tokens_in: int | None = None,
    llm_tokens_out: int | None = None,
    queue_max_age_s: float | None = None,
    pool_max_checked_out: int | None = None,
) -> AdminMetricsDaily:
    """写/覆盖一行的日快照（按日期幂等；跨日落日与回填共用）。"""
    if business is None:
        business = compute_daily_business(session, day)
    from app.models import get_datetime_utc

    row = session.get(AdminMetricsDaily, day)
    if row is None:
        row = AdminMetricsDaily(day=day)
        session.add(row)
    for key, value in business.items():
        setattr(row, key, value)
    # 运行时峰值只在有样本时覆盖（回填不写、空采样不抹掉已有值）
    if llm_calls_by_kind is not None:
        row.llm_calls_by_kind = llm_calls_by_kind
    if provider_failures is not None:
        row.provider_failures = provider_failures
    if llm_tokens_in is not None:
        row.llm_tokens_in = llm_tokens_in
    if llm_tokens_out is not None:
        row.llm_tokens_out = llm_tokens_out
    if queue_max_age_s is not None:
        row.queue_max_age_s = queue_max_age_s
    if pool_max_checked_out is not None:
        row.pool_max_checked_out = pool_max_checked_out
    row.updated_at = get_datetime_utc()
    session.commit()
    session.refresh(row)
    return row


def backfill_history(session: Session, today: date) -> int:
    """补齐 [最早作答日, 昨天] 缺失的快照行（只业务量），返回补行数。"""
    first = (
        session.connection()
        .execute(
            select(
                func.min(
                    func.date(
                        func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at))
                    )
                )
            )
        )
        .scalar_one()
    )
    if first is None:
        return 0
    # 最多回看 BACKFILL_MAX_DAYS 天（max 取两者中较晚者，限制回填起点）
    first = max(first, today - timedelta(days=BACKFILL_MAX_DAYS))
    existing: set[date] = set()
    for d in session.connection().execute(select(col(AdminMetricsDaily.day))).scalars():
        existing.add(d)
    written = 0
    day = first
    last = today - timedelta(days=1)
    while day <= last:
        if day not in existing:
            upsert_daily_snapshot(session, day)
            written += 1
        day += timedelta(days=1)
    if written:
        logger.info("metrics daily backfilled %d rows", written)
    return written


class _DayPeakTracker:
    """当日运行时峰值：60s 采样，**每次采样即落当日行**（部署重启不丢）。

    重启携带：首次采样把当日已落库的增量读作 carry，本进程日增量 =
    carry + (进程计数器 - 进程内基线)；峰值取 max(已落库, 本次采样)。
    写库永远写真值 dict（空 dict = 采样过且为零），与回填的 null
    （当日无采样）区分。
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.queue_max_age_s: float | None = None
        self.pool_max_checked_out: int | None = None
        self.llm_calls_by_kind: dict[str, int] = {}
        self.provider_failures: dict[str, int] = {}
        self.llm_tokens_in = 0
        self.llm_tokens_out = 0
        self._baseline: dict[str, dict[str, float]] | None = None
        self._token_baseline: dict[str, dict[str, int]] | None = None
        self._carry_tokens_in = 0
        self._carry_tokens_out = 0
        self._carry_llm: dict[str, int] | None = None
        self._carry_fail: dict[str, int] | None = None

    def _load_carry(self, session: Session, today: date) -> None:
        row = session.get(AdminMetricsDaily, today)
        self._carry_llm = (
            dict(row.llm_calls_by_kind) if row and row.llm_calls_by_kind else {}
        )
        self._carry_fail = (
            dict(row.provider_failures) if row and row.provider_failures else {}
        )
        if row:
            if row.queue_max_age_s is not None:
                self.queue_max_age_s = row.queue_max_age_s
            if row.pool_max_checked_out is not None:
                self.pool_max_checked_out = row.pool_max_checked_out
            if row.llm_tokens_in is not None:
                self._carry_tokens_in = row.llm_tokens_in
            if row.llm_tokens_out is not None:
                self._carry_tokens_out = row.llm_tokens_out

    def sample(self, session: Session) -> None:
        """采样一次并立即落当日行（upsert 幂等）。"""
        from app.core import db as _db
        from app.core.metrics import call_stats

        today = datetime.now(_tz()).date()
        if self._carry_llm is None or self._carry_fail is None:
            self._load_carry(session, today)
        carry_llm: dict[str, int] = self._carry_llm or {}
        carry_fail: dict[str, int] = self._carry_fail or {}

        # 峰值：最老排队年龄（评分堆积告警的核心数）与连接池水位
        oldest = (
            session.connection()
            .execute(
                select(func.min(col(Attempt.created_at))).where(
                    col(Attempt.status) == AttemptStatus.QUEUED
                )
            )
            .scalar_one()
        )
        if oldest is not None:
            age = (datetime.now(oldest.tzinfo) - oldest).total_seconds()
            self.queue_max_age_s = (
                max(self.queue_max_age_s, age)
                if self.queue_max_age_s is not None
                else age
            )
        checked_out = _db.engine.pool.checkedout()
        self.pool_max_checked_out = (
            max(self.pool_max_checked_out, checked_out)
            if self.pool_max_checked_out is not None
            else checked_out
        )

        # 计数器增量 = carry(当日已落库) + (进程计数器 - 进程内基线)
        stats = call_stats()
        self._baseline = self._baseline or {}
        proc_kind: dict[str, int] = {}
        proc_fail: dict[str, int] = {}
        for kind, values in stats.items():
            base = self._baseline.get(kind)
            calls_delta = values.get("calls", 0) - (base or {}).get("calls", 0)
            fail_delta = values.get("failures", 0) - (base or {}).get("failures", 0)
            if calls_delta < 0 or fail_delta < 0:  # 计数器重启：重置基线
                self._baseline[kind] = dict(values)
                calls_delta = 0
                fail_delta = 0
            if kind.startswith("llm") and calls_delta:
                proc_kind[kind] = int(calls_delta)
            if fail_delta:
                bucket = "llm" if kind.startswith("llm") else kind
                proc_fail[bucket] = proc_fail.get(bucket, 0) + int(fail_delta)
        # 日累计 = carry + 本进程增量（bucket 级合并，避免多 kind 重复带 carry）
        self.llm_calls_by_kind = {
            k: carry_llm.get(k, 0) + proc_kind.get(k, 0)
            for k in {*carry_llm, *proc_kind}
        }
        self.provider_failures = {
            b: carry_fail.get(b, 0) + proc_fail.get(b, 0)
            for b in {*carry_fail, *proc_fail}
        }

        # LLM 真实 token 日累计 = carry(当日已落库) + 进程增量
        from app.core.metrics import llm_token_stats

        tokens = llm_token_stats()
        self._token_baseline = self._token_baseline or {}
        proc_in = proc_out = 0
        for kind, entry in tokens.items():
            base = self._token_baseline.get(kind) or {"in": 0, "out": 0}
            d_in = entry["in"] - base["in"]
            d_out = entry["out"] - base["out"]
            if d_in < 0 or d_out < 0:  # 计数器重启：重置基线
                self._token_baseline[kind] = dict(entry)
                d_in = d_out = 0
            proc_in += d_in
            proc_out += d_out
        self.llm_tokens_in = self._carry_tokens_in + proc_in
        self.llm_tokens_out = self._carry_tokens_out + proc_out

        # 采样即落库：重启前的峰值/增量不因部署丢失
        upsert_daily_snapshot(
            session,
            today,
            llm_calls_by_kind=dict(self.llm_calls_by_kind),
            provider_failures=dict(self.provider_failures),
            llm_tokens_in=self.llm_tokens_in,
            llm_tokens_out=self.llm_tokens_out,
            queue_max_age_s=self.queue_max_age_s,
            pool_max_checked_out=self.pool_max_checked_out,
        )


_tracker: _DayPeakTracker | None = None
_thread_stop: threading.Event | None = None
_thread: threading.Thread | None = None


_alert_sent_day: date | None = None


def maybe_alert_queue_age(queue_max_age_s: float | None) -> bool:
    """队列最老排队超阈值时发告警邮件（当日限一封）。

    收件人 COST_ALERT_EMAIL 留空 = 告警邮件关闭（面板红黄标始终有效）。
    返回是否发出。测试通过替换 utils.send_email 验证。
    """
    global _alert_sent_day
    from app.core.config import settings

    today = datetime.now(_tz()).date()
    if (
        not settings.COST_ALERT_EMAIL
        or queue_max_age_s is None
        or queue_max_age_s < settings.ALERT_QUEUE_AGE_S
    ):
        return False
    if _alert_sent_day == today:
        return False
    from app.utils import send_email

    try:
        send_email(
            email_to=settings.COST_ALERT_EMAIL,
            subject=("[speakup] 评分队列堆积告警 / scoring queue backlog alert"),
            html_content=(
                f"<p>评分队列最老排队已 {int(queue_max_age_s / 60)} 分钟"
                f"（阈值 {settings.ALERT_QUEUE_AGE_S // 60} 分钟）。</p>"
                "<p>请查看管理端大盘「性能与稳定」区，并确认评分 worker 状态。</p>"
                "<p>Oldest queued scoring attempt has exceeded the alert "
                "threshold. Check the admin dashboard performance zone.</p>"
            ),
        )
    except Exception:  # noqa: BLE001 - 邮件失败不影响采样线程
        logger.exception("queue age alert email failed")
        return False
    _alert_sent_day = today
    return True


def _daily_loop(stop_event: threading.Event) -> None:
    tz = _tz()
    current_day = datetime.now(tz).date()
    assert _tracker is not None
    while not stop_event.wait(SAMPLE_INTERVAL_S):
        from app.core.db import engine

        try:
            now_day = datetime.now(tz).date()
            with Session(engine) as session:
                if now_day != current_day:
                    # 跨日：峰值/增量重新起算（昨日行已在历次采样中落库）
                    _tracker.reset()
                    current_day = now_day
                    continue
                _tracker.sample(session)
                maybe_alert_queue_age(_tracker.queue_max_age_s)
        except Exception:  # noqa: BLE001 - 采样是兜底，失败只记日志
            logger.exception("metrics daily sample failed")


def start_metrics_daily() -> None:
    """启动日快照线程（main lifespan 调用；含启动回填）。"""
    global _tracker, _thread_stop, _thread
    if _thread is not None and _thread.is_alive():
        return
    from app.core.db import engine

    _tracker = _DayPeakTracker()
    tz = _tz()
    try:
        with Session(engine) as session:
            backfill_history(session, datetime.now(tz).date())
    except Exception:  # noqa: BLE001 - 回填失败不阻塞启动
        logger.exception("metrics daily backfill failed at startup")
    _thread_stop = threading.Event()
    _thread = threading.Thread(
        target=_daily_loop, args=(_thread_stop,), name="metrics-daily", daemon=True
    )
    _thread.start()


def stop_metrics_daily() -> None:
    global _tracker, _thread_stop, _thread
    if _thread_stop is not None:
        _thread_stop.set()
    _tracker = None
    _thread_stop = None
    _thread = None
