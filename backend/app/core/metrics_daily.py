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
    day_expr = func.date(
        func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at))
    )
    a = session.connection().execute(
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
    ).one()
    sessions = session.connection().execute(
        select(func.count())
        .select_from(PracticeSession)
        .where(col(PracticeSession.session_date) == day)
    ).scalar_one()
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
    llm_calls_by_kind: dict[str, int] | None = None,
    provider_failures: dict[str, int] | None = None,
    queue_max_age_s: float | None = None,
    pool_max_checked_out: int | None = None,
) -> AdminMetricsDaily:
    """写/覆盖一行的日快照（按日期幂等；跨日落日与回填共用）。"""
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
    first = session.connection().execute(
        select(
            func.min(
                func.date(
                    func.timezone(
                        settings.PRACTICE_TZ, col(Attempt.created_at)
                    )
                )
            )
        )
    ).scalar_one()
    if first is None:
        return 0
    # 最多回看 BACKFILL_MAX_DAYS 天（max 取两者中较晚者，限制回填起点）
    first = max(first, today - timedelta(days=BACKFILL_MAX_DAYS))
    existing: set[date] = set()
    for d in session.connection().execute(
        select(col(AdminMetricsDaily.day))
    ).scalars():
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
    """当日运行时峰值：60s 采样的内存最大值 + 计数器日增量（重启容忍）。"""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.queue_max_age_s: float | None = None
        self.pool_max_checked_out: int | None = None
        self.llm_calls_by_kind: dict[str, int] = {}
        self.provider_failures: dict[str, int] = {}
        self._baseline: dict[str, dict[str, float]] | None = None

    def sample(self, session: Session) -> None:
        from app.core import db as _db
        from app.core.metrics import call_stats

        # 队列最老年龄（评分堆积告警的核心数）
        oldest = session.connection().execute(
            select(func.min(col(Attempt.created_at))).where(
                col(Attempt.status) == AttemptStatus.QUEUED
            )
        ).scalar_one()
        if oldest is not None:
            age = (datetime.now(oldest.tzinfo) - oldest).total_seconds()
            self.queue_max_age_s = (
                max(self.queue_max_age_s, age)
                if self.queue_max_age_s is not None
                else age
            )
        # 连接池水位
        pool = _db.engine.pool
        checked_out = pool.checkedout()
        self.pool_max_checked_out = (
            max(self.pool_max_checked_out, checked_out)
            if self.pool_max_checked_out is not None
            else checked_out
        )
        # 计数器日增量：now - 当日基线（重启后 now < baseline 时基线重置）
        stats = call_stats()
        if self._baseline is None:
            self._baseline = {k: dict(v) for k, v in stats.items()}
        deltas_kind: dict[str, int] = {}
        deltas_fail: dict[str, int] = {}
        for kind, values in stats.items():
            base = self._baseline.get(kind)
            calls_delta = values.get("calls", 0) - (base or {}).get("calls", 0)
            fail_delta = values.get("failures", 0) - (base or {}).get(
                "failures", 0
            )
            if calls_delta < 0 or fail_delta < 0:  # 计数器重启：重置基线
                self._baseline[kind] = dict(values)
                calls_delta = 0
                fail_delta = 0
            if kind.startswith("llm") and calls_delta:
                deltas_kind[kind] = int(calls_delta)
            if fail_delta:
                bucket = "llm" if kind.startswith("llm") else kind
                deltas_fail[bucket] = deltas_fail.get(bucket, 0) + int(fail_delta)
        # 增量按日累计（多次采样求和会重复：改为 now - 当日零点基线，直接覆盖）
        self.llm_calls_by_kind = deltas_kind
        self.provider_failures = deltas_fail


_tracker: _DayPeakTracker | None = None
_thread_stop: threading.Event | None = None
_thread: threading.Thread | None = None


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
                    # 跨日：落昨日快照（业务量 + 当日峰值），峰值重新起算
                    upsert_daily_snapshot(
                        session,
                        current_day,
                        llm_calls_by_kind=_tracker.llm_calls_by_kind or None,
                        provider_failures=_tracker.provider_failures or None,
                        queue_max_age_s=_tracker.queue_max_age_s,
                        pool_max_checked_out=_tracker.pool_max_checked_out,
                    )
                    _tracker.reset()
                    current_day = now_day
                    continue
                _tracker.sample(session)
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
