"""大盘日快照：业务量回算 / 幂等 upsert / 回填 / performance 端点门与形状。"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.core.config import settings
from app.core.metrics_daily import (
    BUSINESS_REFRESH_SAMPLES,
    backfill_history,
    upsert_daily_snapshot,
)
from app.models import (
    AdminCostReconcile,
    AdminMetricsDaily,
    Attempt,
    PracticeSession,
)
from tests.utils.credential import make_student

tz = ZoneInfo(settings.PRACTICE_TZ)


def _purge(db: Session) -> None:
    db.exec(delete(Attempt))  # type: ignore[call-overload]
    db.exec(delete(PracticeSession))  # type: ignore[call-overload]
    db.exec(delete(AdminMetricsDaily))  # type: ignore[call-overload]
    db.exec(delete(AdminCostReconcile))  # type: ignore[call-overload]
    db.commit()


def _attempt(
    db: Session,
    student_id: uuid.UUID,
    day: date,
    *,
    status: str,
    dur: float = 5.0,
    item_type: str = "question",
) -> None:
    db.add(
        Attempt(
            item_type=item_type,
            item_id=uuid.uuid4(),
            student_id=student_id,
            audio_path="t.webm",
            duration_s=dur,
            status=status,
            created_at=datetime.combine(day, datetime.min.time().replace(hour=10), tz),
        )
    )
    db.flush()


def test_daily_snapshot_business_and_upsert_idempotent(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    ada = make_student(db, client, classroom["code"], "Ada")
    today = datetime.now(tz).date()
    day = today - timedelta(days=1)

    ada_id = uuid.UUID(ada["student"]["id"])
    _attempt(db, ada_id, day, status="done", dur=5.0)
    _attempt(db, ada_id, day, status="done", dur=7.0)
    _attempt(db, ada_id, day, status="failed", dur=3.0)
    db.add(
        PracticeSession(
            classroom_id=uuid.UUID(classroom["id"]),
            student_id=ada_id,
            band="B1",
            session_date=day,
        )
    )
    db.commit()

    row = upsert_daily_snapshot(db, day)
    assert row.attempts == 3
    assert row.attempts_done == 2
    assert row.attempts_failed == 1
    assert row.active_students == 1
    assert row.sessions == 1
    assert row.asr_seconds == 15.0
    assert row.queue_max_age_s is None  # 回算不带峰值

    # 再写一次（带峰值）→ 覆盖业务量、补上峰值；日期幂等不建新行
    row2 = upsert_daily_snapshot(db, day, queue_max_age_s=42.0, pool_max_checked_out=3)
    assert row2.attempts == 3
    assert row2.queue_max_age_s == 42.0
    count = len(db.exec(select(AdminMetricsDaily)).all())
    assert count == 1


def test_backfill_only_missing_rows(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    ada = make_student(db, client, classroom["code"], "Ada")
    today = datetime.now(tz).date()
    day3 = today - timedelta(days=3)
    _attempt(db, uuid.UUID(ada["student"]["id"]), day3, status="done")

    db.commit()

    written = backfill_history(db, today)
    # 只补有作答的日子（空洞日不建零行——月账单聚合不受缺日影响）
    assert written == 1
    row3 = db.get(AdminMetricsDaily, day3)
    assert row3 is not None and row3.attempts == 1
    # 回填补 LLM 估算：1 条 done 问答题 → llm_rubric 1 次
    assert row3.llm_calls_by_kind == {"llm_rubric": 1}
    assert db.get(AdminMetricsDaily, today - timedelta(days=2)) is None

    # 再跑一遍：全部已存在，零写入（新行）
    assert backfill_history(db, today) == 0

    # 复审：P1 时期建的存量行（llm 为 null）要被补上估算，非 null 不动
    day2 = today - timedelta(days=2)
    stale = AdminMetricsDaily(day=day2)
    session_kwargs = {
        "attempts": 0,
        "attempts_done": 0,
        "attempts_failed": 0,
        "active_students": 0,
        "sessions": 0,
        "asr_seconds": 0.0,
    }
    for k, v in session_kwargs.items():
        setattr(stale, k, v)
    db.add(stale)
    db.commit()
    # day3 有 1 条 done 问答题：给 day3 造一条「采样器写过」的行（非 null），
    # 业务量列同时埋一个哨兵值，验证回填会刷新业务量但不碰 LLM 列
    sampled = db.get(AdminMetricsDaily, day3)
    assert sampled is not None
    sampled.llm_calls_by_kind = {"llm_rubric": 99}
    sampled.attempts = 9999
    db.commit()

    backfill_history(db, today)
    refreshed_stale = db.get(AdminMetricsDaily, day2)
    assert refreshed_stale is not None
    # day2 无作答 → 不在 agg，行未被动过（SQL NULL 语义位保持）
    assert refreshed_stale.llm_calls_by_kind is None
    # day3 存量非 null → 不被回填估算覆盖；业务量列 → 被精确回算刷新
    sampled_row = db.get(AdminMetricsDaily, day3)
    assert sampled_row is not None
    assert sampled_row.llm_calls_by_kind == {"llm_rubric": 99}
    assert sampled_row.attempts == 1

    # 换一个有作答但行是 null 的日子：backfill 应补上估算
    day1 = today - timedelta(days=1)
    _attempt(db, uuid.UUID(ada["student"]["id"]), day1, status="done")
    db.commit()
    backfill_history(db, today)
    row1 = db.get(AdminMetricsDaily, day1)
    assert row1 is not None
    assert row1.llm_calls_by_kind == {"llm_rubric": 1}

    # 有作答但全非问答题（朗读/跟读）的日子：回算为 {} 而非 None——
    # JSON 列写 None 会落成 JSON 'null'（测试里给该列赋 None 亦然），
    # 破坏 SQL NULL=未处理的语义位
    repeat_day = today - timedelta(days=5)
    _attempt(
        db,
        uuid.UUID(ada["student"]["id"]),
        repeat_day,
        status="done",
        item_type="repeat",
    )
    db.commit()
    backfill_history(db, today)
    row_r = db.get(AdminMetricsDaily, repeat_day)
    assert row_r is not None
    assert row_r.llm_calls_by_kind == {}


def test_performance_endpoint_gates_and_shape(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    _purge(db)
    yesterday = datetime.now(tz).date() - timedelta(days=1)
    upsert_daily_snapshot(db, yesterday, queue_max_age_s=10.0)

    # 401 / 403
    assert client.get("/api/v1/admin/dashboard/performance").status_code == 401
    from app import crud
    from app.models import UserCreate
    from tests.utils.utils import random_email, random_lower_string

    email, password = random_email(), random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    teacher = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert teacher.status_code == 200
    headers = {"Authorization": f"Bearer {teacher.json()['access_token']}"}
    assert (
        client.get("/api/v1/admin/dashboard/performance", headers=headers).status_code
        == 403
    )

    resp = client.get(
        "/api/v1/admin/dashboard/performance?days=7",
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 实时快照与 /admin/metrics 同构
    assert {"scoring", "providers", "audio_storage", "db_pool"} <= set(body["realtime"])
    assert "by_status" in body["realtime"]["scoring"]
    # 历史行形状
    assert [h["date"] for h in body["history"]] == [yesterday.isoformat()]
    assert body["history"][0]["queue_max_age_s"] == 10.0
    assert body["runtime_issues_today"] == 0


def test_pool_stats_expose_capacity_and_worker_tri_state(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """评审返修：池水位分母必须是配置容量；worker 红标只看 stopped 三态。"""
    resp = client.get("/api/v1/admin/metrics", headers=superuser_token_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert (
        body["db_pool"]["capacity"]
        == body["db_pool"]["pool_size"] + body["db_pool"]["max_overflow"]
    )
    assert body["db_pool"]["capacity"] >= 1
    # 测试进程未终局关闭：idle 或 running，绝不是 stopped
    assert body["scoring"]["executor_state"] in ("idle", "running")


def test_daily_snapshot_carry_across_tracker_restart(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """评审返修：采样即落库 + 重启 carry——新进程的较小计数不覆盖当日累计。"""
    from app.core import metrics as m
    from app.core.metrics_daily import _DayPeakTracker

    _purge(db)
    m.reset_for_tests()  # 增量基线从零起算：先清共享计数器，防全套污染
    today = datetime.now(tz).date()

    # 第一段进程生命：落了当日行（llm 5 次调用、2 失败、池峰 4）
    upsert_daily_snapshot(
        db,
        today,
        llm_calls_by_kind={"llm_rubric": 5},
        provider_failures={"llm": 2},
        pool_max_checked_out=4,
        queue_max_age_s=12.0,
    )

    # 「重启」：新 tracker 首次采样 carry 旧值，不覆盖
    tracker = _DayPeakTracker()
    tracker.sample(db)
    row = db.get(AdminMetricsDaily, today)
    assert row is not None
    assert row.llm_calls_by_kind == {"llm_rubric": 5}  # carry 保留，未被 0 覆盖
    assert row.provider_failures == {"llm": 2}
    # 峰值不回退；空 dict/真值区分由采样路径写真值保证
    assert row.pool_max_checked_out == 4
    assert row.queue_max_age_s == 12.0
    m.reset_for_tests()


def test_sample_recomputes_business_hourly_not_per_sample(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """采样降频回算：首采落当日业务量；中间采样只落峰值、不回算（业务量
    列原样保留）；每 BUSINESS_REFRESH_SAMPLES 次（约一小时）回算刷新。"""
    from app.core import metrics as m
    from app.core.metrics_daily import _DayPeakTracker

    _purge(db)
    m.reset_for_tests()  # 共享计数器清零，防全套污染
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    ada = make_student(db, client, classroom["code"], "Ada")
    today = datetime.now(tz).date()
    _attempt(db, uuid.UUID(ada["student"]["id"]), today, status="done")
    db.commit()

    tracker = _DayPeakTracker()
    tracker.sample(db)  # 首采（samples=1）：回算业务量
    row = db.get(AdminMetricsDaily, today)
    assert row is not None and row.attempts == 1

    # 中间采样不回算：业务量列若被回算会把哨兵覆盖回 1
    row.attempts = 9999
    db.add(row)
    db.commit()
    tracker.sample(db)  # samples=2：非刷新点
    db.refresh(row)
    assert row.attempts == 9999

    # 刷新点（samples 达 BUSINESS_REFRESH_SAMPLES）：回算覆盖哨兵
    tracker.samples = BUSINESS_REFRESH_SAMPLES - 1
    tracker.sample(db)
    db.refresh(row)
    assert row.attempts == 1
    m.reset_for_tests()


def test_day_bounds_utc_handles_dst_timezone(monkeypatch) -> None:
    """DST 防御（评审可选项）：端点各按当日零点换算——夏令时进入日区间
    23h 而非固定 24h，且端点 UTC 时刻对齐当地零点。"""
    from app.core import metrics_daily

    monkeypatch.setattr(settings, "PRACTICE_TZ", "America/New_York")
    # 2026-03-08 是美东夏令时进入日（02:00 → 03:00）：当日 23h
    start, end = metrics_daily._day_bounds_utc(date(2026, 3, 8))
    assert (end - start) == timedelta(hours=23)
    from datetime import UTC

    assert start == datetime(2026, 3, 8, 5, 0, tzinfo=UTC)  # EST 零点 = 05:00Z
    assert end == datetime(2026, 3, 9, 4, 0, tzinfo=UTC)  # 次日 EDT 零点 = 04:00Z
    # 非切换日 24h；固定偏移时区（生产 Asia/Shanghai）恒 24h
    s2, e2 = metrics_daily._day_bounds_utc(date(2026, 3, 15))
    assert (e2 - s2) == timedelta(hours=24)
    monkeypatch.setattr(settings, "PRACTICE_TZ", "Asia/Shanghai")
    s, e = metrics_daily._day_bounds_utc(date(2026, 3, 8))
    assert (e - s) == timedelta(hours=24)


def test_cost_endpoint_and_reconcile(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """费用区：月度估算数学 + 对账录入与偏差 + 权限门。"""
    from app.core.config import settings as cfg
    from app.models import AdminCostReconcile

    _purge(db)
    today = datetime.now(tz).date()
    this_month = f"{today.year:04d}-{today.month:02d}"
    # 本月 2 条快照：合计 3600s ASR（=1h → ¥4.5）、llm 100 次调用
    for day in (today - timedelta(days=1), today):
        upsert_daily_snapshot(
            db,
            day,
            business={
                "attempts": 10,
                "attempts_done": 10,
                "attempts_failed": 0,
                "active_students": 5,
                "sessions": 2,
                "asr_seconds": 1800.0,
            },
            llm_calls_by_kind={"llm_rubric": 50},
        )

    # 401 / 403
    assert client.get("/api/v1/admin/dashboard/cost").status_code == 401
    resp = client.get("/api/v1/admin/dashboard/cost", headers=superuser_token_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    months = {m["month"]: m for m in body["months"]}
    assert this_month in months
    m = months[this_month]
    assert m["asr_seconds"] == 3600.0
    assert m["llm_calls"] == 100
    assert m["asr_cny"] == round(cfg.COST_ASR_CNY_PER_HOUR, 2)
    per_call = (
        cfg.COST_LLM_CNY_PER_MTOK_IN * cfg.COST_LLM_EST_TOKENS_IN
        + cfg.COST_LLM_CNY_PER_MTOK_OUT * cfg.COST_LLM_EST_TOKENS_OUT
    ) / 1_000_000
    assert m["llm_cny"] == round(100 * per_call, 2)
    assert m["total_cny"] == round(m["asr_cny"] + m["llm_cny"] + m["server_cny"], 2)
    assert m["attempts"] == 20
    assert m["actual_cny"] is None

    # 对账录入（合法月份 + 非法月份）
    resp = client.put(
        "/api/v1/admin/dashboard/cost/reconcile",
        json={"month": this_month, "amount_cny": 260.0},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200
    assert (
        client.put(
            "/api/v1/admin/dashboard/cost/reconcile",
            json={"month": "2026-13", "amount_cny": 1.0},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )

    resp = client.get("/api/v1/admin/dashboard/cost", headers=superuser_token_headers)
    m = {x["month"]: x for x in resp.json()["months"]}[this_month]
    assert m["actual_cny"] == 260.0
    assert m["deviation_pct"] is not None
    assert db.get(AdminCostReconcile, this_month) is not None


def test_current_queue_age_s(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """告警基数是当前排队年龄：无排队 None；有排队为正数。"""
    from app.core.metrics_daily import current_queue_age_s

    _purge(db)
    assert current_queue_age_s(db) is None
    db.add(
        Attempt(
            item_type="question",
            item_id=uuid.uuid4(),
            audio_path="t.webm",
            duration_s=3.0,
            status="queued",
            created_at=datetime.now(tz) - timedelta(minutes=3),
        )
    )
    db.commit()
    age = current_queue_age_s(db)
    assert age is not None and 170 < age < 200


def test_queue_age_alert_rate_limited(monkeypatch) -> None:
    """队列告警：超阈发信、当日限一封、阈值内不发、未配置收件人关闭。"""
    from app.core import metrics_daily
    from app.core.config import settings as cfg

    sent: list[str] = []
    monkeypatch.setattr(settings, "COST_ALERT_EMAIL", "ops@example.com")
    monkeypatch.setattr(
        "app.utils.send_email", lambda **kw: sent.append(kw["email_to"])
    )
    # 重置当日限频标记
    metrics_daily._alert_sent_day = None

    # 未超阈：不发
    assert metrics_daily.maybe_alert_queue_age(60) is False
    assert sent == []
    # 超阈：发一次；当日再超：限频
    assert metrics_daily.maybe_alert_queue_age(cfg.ALERT_QUEUE_AGE_S + 1) is True
    assert sent == ["ops@example.com"]
    assert metrics_daily.maybe_alert_queue_age(cfg.ALERT_QUEUE_AGE_S + 999) is False
    assert len(sent) == 1
    # 未配置收件人：关闭
    monkeypatch.setattr(settings, "COST_ALERT_EMAIL", "")
    metrics_daily._alert_sent_day = None
    assert metrics_daily.maybe_alert_queue_age(cfg.ALERT_QUEUE_AGE_S + 1) is False
    monkeypatch.setattr(settings, "COST_ALERT_EMAIL", None)
    assert metrics_daily.maybe_alert_queue_age(cfg.ALERT_QUEUE_AGE_S + 1) is False


def test_llm_token_accumulator_and_reset() -> None:
    """token 累加器：按 kind 累计、快照拷贝、reset 清空、负值钳零。"""
    from app.core import metrics as m

    m.reset_for_tests()
    try:
        m.record_llm_tokens("llm_rubric", prompt_tokens=100, completion_tokens=50)
        m.record_llm_tokens("llm_rubric", prompt_tokens=30, completion_tokens=20)
        m.record_llm_tokens("llm_vocab_explain", prompt_tokens=10, completion_tokens=5)
        m.record_llm_tokens("llm_rubric", prompt_tokens=-5, completion_tokens=0)
        stats = m.llm_token_stats()
        assert stats["llm_rubric"] == {"in": 130, "out": 70}
        assert stats["llm_vocab_explain"] == {"in": 10, "out": 5}
    finally:
        m.reset_for_tests()
    assert m.llm_token_stats() == {}


def test_ark_chat_records_usage_tokens(monkeypatch) -> None:
    """ArkChatClient.chat 成功响应的 usage → token 记账；缺 usage 不炸。"""
    import httpx

    from app.core import metrics as m
    from app.scoring.ark_client import ArkChatClient

    m.reset_for_tests()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 80},
            },
        )

    def handler_no_usage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = ArkChatClient(
        api_key="k",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.chat("s", "u", metric_kind="llm_rubric") == "ok"
    assert m.llm_token_stats()["llm_rubric"] == {"in": 120, "out": 80}

    client2 = ArkChatClient(
        api_key="k",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler_no_usage)),
    )
    assert client2.chat("s", "u", metric_kind="llm_x") == "ok"
    assert m.llm_token_stats()["llm_x"] == {"in": 0, "out": 0}
    m.reset_for_tests()


def test_cost_prefers_real_tokens_with_fallback(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """费用区 LLM：全调用日有 token → 真实计费；无 token → 估算回退。"""
    from app.core.config import settings as cfg

    _purge(db)
    today = datetime.now(tz).date()
    month = f"{today.year:04d}-{today.month:02d}"

    # 昨日：100 次调用 + 真实 token 记账（当日全记账 → tokens 基数）
    upsert_daily_snapshot(
        db,
        today - timedelta(days=1),
        business={
            "attempts": 5,
            "attempts_done": 5,
            "attempts_failed": 0,
            "active_students": 3,
            "sessions": 1,
            "asr_seconds": 0.0,
        },
        llm_calls_by_kind={"llm_rubric": 100},
        llm_tokens_in=60_000,
        llm_tokens_out=60_000,
    )
    # 今日：20 次调用、未记账（采样线程未跑）→ 该月混算 → 回退估算
    upsert_daily_snapshot(
        db,
        today,
        business={
            "attempts": 2,
            "attempts_done": 2,
            "attempts_failed": 0,
            "active_students": 2,
            "sessions": 1,
            "asr_seconds": 0.0,
        },
        llm_calls_by_kind={"llm_rubric": 20},
    )
    resp = client.get("/api/v1/admin/dashboard/cost", headers=superuser_token_headers)
    m = {x["month"]: x for x in resp.json()["months"]}[month]
    # 调用日 2 天、记账日 1 天 → 未全覆盖 → 估算
    assert m["llm_basis"] == "estimated"
    assert m["llm_tokens_in"] is None

    # 把今日也补上 token → 全覆盖 → 真实计费
    upsert_daily_snapshot(
        db,
        today,
        llm_calls_by_kind={"llm_rubric": 20},
        llm_tokens_in=12_000,
        llm_tokens_out=12_000,
    )
    resp = client.get("/api/v1/admin/dashboard/cost", headers=superuser_token_headers)
    m = {x["month"]: x for x in resp.json()["months"]}[month]
    assert m["llm_basis"] == "tokens"
    assert m["llm_tokens_in"] == 72_000
    assert m["llm_tokens_out"] == 72_000
    expected = round(
        72_000 / 1_000_000 * cfg.COST_LLM_CNY_PER_MTOK_IN
        + 72_000 / 1_000_000 * cfg.COST_LLM_CNY_PER_MTOK_OUT,
        2,
    )
    assert m["llm_cny"] == expected


def test_tracker_token_carry_across_restart(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """token 日累计的重启 carry：新进程不覆盖当日已记 token。"""
    from app.core import metrics as m
    from app.core.metrics_daily import _DayPeakTracker

    _purge(db)
    m.reset_for_tests()
    today = datetime.now(tz).date()
    upsert_daily_snapshot(db, today, llm_tokens_in=1000, llm_tokens_out=600)
    # 「重启」后新进程记了 200/100
    m.record_llm_tokens("llm_rubric", prompt_tokens=200, completion_tokens=100)
    tracker = _DayPeakTracker()
    tracker.sample(db)
    row = db.get(AdminMetricsDaily, today)
    assert row is not None
    assert row.llm_tokens_in == 1200  # carry 1000 + 200
    assert row.llm_tokens_out == 700
    # 孤儿音频数随采样落当日行（复用 metrics 的缓存统计，此处至少非空）
    assert isinstance(row.audio_orphans, int)
    m.reset_for_tests()


def test_intentional_failure_for_required_check_verification():
    """临时实证用例：验证必需检查项会阻塞后端检查挂掉的 PR。验证后即删。"""
    assert False, "intentional failure for required-check verification"
