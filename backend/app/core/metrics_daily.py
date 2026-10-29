"""大盘日快照：业务量回算 + 运行时峰值采样，每日一行落 admin_metrics_daily。

解决 /admin/metrics 两件事：进程计数器重启归零、没有历史。业务量（作答/
活跃/会话/ASR 秒数）从明细表回算，但不是每分钟：首采、每小时与跨日落定
时各算一次（聚合查询不宜进 60s 循环）；运行时峰值（最老排队年龄、连接池
水位、引擎失败数）由本线程 60s 采样在内存里记最大值，跨日时写回。

线程每天跨日（PRACTICE_TZ）落一行昨日快照；启动时回填缺失的历史行
（只回算业务量，峰值为 null——重启前的峰值无法追溯）。
"""

import logging
import threading
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlmodel import Session, col

from app.core.config import settings
from app.models import (
    AdminMetricsDaily,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    PracticeSession,
)

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_S = 60
BACKFILL_MAX_DAYS = 400
# 业务量回算频率：首次采样立即算一次（进程重启后当日行不空窗），
# 之后每 N 次采样（约一小时）刷新一次；跨日时对昨日精确落定
BUSINESS_REFRESH_SAMPLES = 60


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """练习日的 UTC 闭开区间 [day 00:00, day+1 00:00)。

    PRACTICE_TZ 为固定偏移时区（Asia/Shanghai 无夏令时）时与
    date(timezone(tz, created_at)) == day 严格等价，且 created_at 上的
    普通索引可用（对 created_at 列套函数不可走索引）。端点各自按当日
    零点换算（而非 start + 1day）：即便未来配成有夏令时的时区，切换日
    也只会偏差当日窗口本身的口径，不会算错固定 24h。
    """
    start = datetime.combine(day, time.min, _tz()).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, _tz()).astimezone(UTC)
    return start, end


def compute_daily_business(session: Session, day: date) -> dict[str, object]:
    """按练习日回算业务量（与大盘 P0 同口径：PRACTICE_TZ 切日）。

    时间过滤用 created_at 的 UTC 区间（可走 ix_attempt_created_at），
    不用 date(timezone(...)) == day（对列套函数，无法走索引）。
    """
    start, end = _day_bounds_utc(day)
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
            ).where(col(Attempt.created_at) >= start, col(Attempt.created_at) < end)
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
    audio_orphans: int | None = None,
) -> AdminMetricsDaily:
    """写/覆盖一行的日快照（按日期幂等；跨日落日与回填共用）。

    business=None 时回算当日业务量并覆盖对应列；传空 dict 表示本轮
    不写业务量列（采样线程降频回算用）。
    """
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
    if audio_orphans is not None:
        row.audio_orphans = audio_orphans
    row.updated_at = get_datetime_utc()
    session.commit()
    session.refresh(row)
    return row


def backfill_history(session: Session, today: date) -> int:
    """补齐 [最早作答日, 昨天] 缺失的快照行（只业务量 + LLM 估算），返回补行数。

    聚合按两条 GROUP BY 一次算完（逐日查询在 lifespan yield 前执行，
    量上来会挡接流量）；无作答的空洞日不补行（月账单服务器费照算，
    缺日不影响费用聚合）；LLM 历史无进程计数器，按「问答题 done ≈ 1 次
    rubric 调用」回算，费用区走估算基数。
    """
    day_expr = func.date(func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at)))
    last = today - timedelta(days=1)
    cap = today - timedelta(days=BACKFILL_MAX_DAYS)
    # 窗口裁剪用 created_at 区间（可走索引）；day_expr 只用于分组标签
    cap_start, _ = _day_bounds_utc(cap)
    _, last_end = _day_bounds_utc(last)
    agg: dict[date, dict[str, object]] = {}
    for row in session.connection().execute(
        select(
            day_expr.label("day"),
            func.count().label("attempts"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.DONE)
            .label("done"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.FAILED)
            .label("failed"),
            func.count(func.distinct(Attempt.student_id)).label("active"),
            func.coalesce(func.sum(Attempt.duration_s), 0.0).label("seconds"),
            func.count()
            .filter(
                col(Attempt.status) == AttemptStatus.DONE,
                col(Attempt.item_type) == AttemptItemType.QUESTION,
            )
            .label("question_done"),
        )
        .where(col(Attempt.created_at) >= cap_start, col(Attempt.created_at) < last_end)
        .group_by(day_expr)
    ):
        agg[row.day] = {
            "attempts": row.attempts,
            "attempts_done": row.done,
            "attempts_failed": row.failed,
            "active_students": row.active,
            "sessions": 0,
            "asr_seconds": round(float(row.seconds), 1),
            "llm_calls_by_kind": (
                {"llm_rubric": row.question_done} if row.question_done else None
            ),
        }
    if not agg:
        return 0
    for row in session.connection().execute(
        select(
            col(PracticeSession.session_date).label("day"),
            func.count().label("sessions"),
        )
        .where(
            col(PracticeSession.session_date) >= min(agg),
            col(PracticeSession.session_date) <= last,
        )
        .group_by(col(PracticeSession.session_date))
    ):
        if row.day in agg:
            agg[row.day]["sessions"] = row.sessions
    # 存量行补 LLM 估算：P1 时期回填建的行没有 llm_calls_by_kind（null），
    # 只插缺行会让历史月 LLM 恒为 ¥0——对 agg 范围内 llm 为 null 的已有行
    # 补估算；采样器写过的不动（非 null 即真实/采样数据）
    patched = 0
    # sqlalchemy 的 select(Model) 走 session.exec 返回 Row 而非实体
    # （sqlmodel 只解包自家 select），取实体一律走 session.scalars
    stale_rows = session.scalars(
        select(AdminMetricsDaily).where(
            col(AdminMetricsDaily.day) >= min(agg),
            col(AdminMetricsDaily.day) <= last,
            col(AdminMetricsDaily.llm_calls_by_kind).is_(None),
        )
    ).all()
    for row in stale_rows:
        a = agg.get(row.day)
        if not a:
            continue
        llm = a["llm_calls_by_kind"]
        # 空估算来源写 {}（回算过、无 LLM 调用）：JSON 列赋 None 会被
        # 序列化成 JSON 'null'，破坏 SQL NULL=未处理的语义位。
        # agg 的 value 是 object，isinstance 收窄后仍是 dict[Unknown]，
        # cast 到列类型（值由 backfill 自建，键为 str、值为 int）
        row.llm_calls_by_kind = (
            cast("dict[str, int]", llm) if isinstance(llm, dict) else {}
        )
        patched += 1
    if patched:
        session.commit()
        logger.info("metrics daily backfilled llm estimate for %d rows", patched)
    existing: set[date] = set()
    from app.models import get_datetime_utc

    refreshed = 0
    for row in session.scalars(
        select(AdminMetricsDaily).where(
            col(AdminMetricsDaily.day) >= min(agg),
            col(AdminMetricsDaily.day) <= last,
        )
    ).all():
        existing.add(row.day)
        a = agg.get(row.day)
        if not a:
            continue
        # 已有行的业务量列刷新到精确回算值：采样线程降频回算后，进程中断
        # 跨日会让该日行停留在最后一次整点回算的值。LLM 列不在此刷新
        # （上方补丁逻辑单独维护真实/估算的语义位）
        row.attempts = cast(int, a["attempts"])
        row.attempts_done = cast(int, a["attempts_done"])
        row.attempts_failed = cast(int, a["attempts_failed"])
        row.active_students = cast(int, a["active_students"])
        row.sessions = cast(int, a["sessions"])
        row.asr_seconds = cast(float, a["asr_seconds"])
        row.updated_at = get_datetime_utc()
        refreshed += 1
    if refreshed:
        session.commit()
        logger.info("metrics daily refreshed business for %d existing rows", refreshed)

    written = 0
    for day in sorted(set(agg) - existing):
        a = agg[day]
        llm = a["llm_calls_by_kind"]
        session.add(
            AdminMetricsDaily(
                day=day,
                attempts=cast(int, a["attempts"]),
                attempts_done=cast(int, a["attempts_done"]),
                attempts_failed=cast(int, a["attempts_failed"]),
                active_students=cast(int, a["active_students"]),
                sessions=cast(int, a["sessions"]),
                asr_seconds=cast(float, a["asr_seconds"]),
                llm_calls_by_kind=cast(
                    "dict[str, int]", llm if isinstance(llm, dict) else {}
                ),
                updated_at=get_datetime_utc(),
            )
        )
        written += 1
    if written:
        session.commit()
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
        self.samples = 0
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

        # 采样即落库：重启前的峰值/增量不因部署丢失。token 只在当日
        # 真有用量时写——0 也是"未记到"，写 0 会把空采样日冒充"已记账"
        # （费用区按调用日覆盖率切计费基数）
        has_tokens = self.llm_tokens_in > 0 or self.llm_tokens_out > 0
        # 孤儿音频数：复用 /admin/metrics 的 60s 缓存统计（不额外扫盘）
        from app.api.routes.metrics import _audio_storage_stats

        orphans = _audio_storage_stats(session).get("orphan_count")
        # 业务量回算是聚合查询，不该每分钟跑：首采（重启后当日行立即有值）
        # 与每 BUSINESS_REFRESH_SAMPLES 次（约一小时）刷新，其余采样只落
        # 运行时峰值；跨日时由 _daily_loop 对昨日精确落定
        self.samples += 1
        business: dict[str, object] = (
            compute_daily_business(session, today)
            if self.samples == 1 or self.samples % BUSINESS_REFRESH_SAMPLES == 0
            else {}
        )
        upsert_daily_snapshot(
            session,
            today,
            business=business,
            llm_calls_by_kind=dict(self.llm_calls_by_kind),
            provider_failures=dict(self.provider_failures),
            llm_tokens_in=self.llm_tokens_in if has_tokens else None,
            llm_tokens_out=self.llm_tokens_out if has_tokens else None,
            queue_max_age_s=self.queue_max_age_s,
            pool_max_checked_out=self.pool_max_checked_out,
            audio_orphans=orphans,
        )


_tracker: _DayPeakTracker | None = None
_thread_stop: threading.Event | None = None
_thread: threading.Thread | None = None


_alert_sent_day: date | None = None


def current_queue_age_s(session: Session) -> float | None:
    """当前最老排队年龄（非当日峰值：峰值经 carry 在重启后仍在，
    队列已清空时不应告警）。"""
    oldest = (
        session.connection()
        .execute(
            select(func.min(col(Attempt.created_at))).where(
                col(Attempt.status) == AttemptStatus.QUEUED
            )
        )
        .scalar_one()
    )
    if oldest is None:
        return None
    return (datetime.now(oldest.tzinfo) - oldest).total_seconds()


def maybe_alert_queue_age(queue_age_s: float | None) -> bool:
    """当前排队年龄超阈值时发告警邮件（当日限一封）。

    收件人 COST_ALERT_EMAIL 留空 = 告警邮件关闭（面板红黄标始终有效）。
    发信由调用方在 Session 关闭之后触发（SMTP 不占数据库连接）。
    返回是否发出。测试通过替换 utils.send_email 验证。
    """
    global _alert_sent_day
    from app.core.config import settings

    today = datetime.now(_tz()).date()
    if (
        not settings.COST_ALERT_EMAIL
        or queue_age_s is None
        or queue_age_s < settings.ALERT_QUEUE_AGE_S
    ):
        return False
    if _alert_sent_day == today:
        return False
    from app.utils import send_email

    try:
        send_email(
            email_to=settings.COST_ALERT_EMAIL,
            subject="「BELP」评分队列堆积告警 / scoring queue backlog",
            html_content=(
                f"<p>评分队列最老排队已 {int(queue_age_s / 60)} 分钟"
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
            queue_age: float | None = None
            with Session(engine) as session:
                if now_day != current_day:
                    # 跨日：先把昨日行业务量精确落定（采样降频回算后当日行
                    # 最多滞后一小时），再重置峰值/增量起算（昨日行的运行时
                    # 峰值已在历次采样中落库，upsert 不传峰值参数不会覆盖）
                    try:
                        upsert_daily_snapshot(session, current_day)
                    except Exception:  # noqa: BLE001 - 落定失败不阻塞采样周期
                        logger.exception(
                            "metrics daily rollover recompute failed for %s",
                            current_day,
                        )
                    _tracker.reset()
                    current_day = now_day
                    continue
                _tracker.sample(session)
                queue_age = current_queue_age_s(session)
            # 发信在 Session 关闭之后（SMTP 不占数据库连接）
            maybe_alert_queue_age(queue_age)
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
