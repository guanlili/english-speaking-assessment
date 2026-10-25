"""运维指标端点（superuser）：评分队列、ASR/LLM 失败率、音频存储量。

甲方使用期出问题时先看这里，不用翻日志猜。进程内计数器重启归零
（见 app/core/metrics.py）；音频目录统计有 60s 缓存（目录可能上万文件）。
不接 Prometheus——没有采集端，JSON 直接 curl 可读；要接时再加文本格式。
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import SessionDep, SuperUserDep
from app.core import db as _db
from app.core.config import settings
from app.core.metrics import call_stats, call_stats_by_prefix
from app.core.request_context import PROCESS_INFO
from app.models import Attempt, AttemptStatus
from app.scoring import worker

router = APIRouter(prefix="/admin/metrics", tags=["admin"])

_audio_cache_lock = threading.Lock()
_audio_cache: dict[str, Any] | None = None
_audio_cached_at = 0.0
_AUDIO_CACHE_TTL_S = 60.0


def _audio_storage_stats(session: Session) -> dict[str, Any]:
    """统计音频目录（含 content/ 标准音）：总字节、文件数与孤儿数。

    孤儿 = 存储根顶层文件中 basename 不被任何 attempt.audio_path 引用
    的数量（删班残留，每日清理循环会回收）；60s 缓存。
    """
    global _audio_cache, _audio_cached_at
    now = time.monotonic()
    with _audio_cache_lock:
        if _audio_cache is not None and now - _audio_cached_at < _AUDIO_CACHE_TTL_S:
            return _audio_cache
    root = Path(settings.AUDIO_STORAGE_DIR)
    total_bytes = 0
    file_count = 0
    top_level: set[str] = set()
    if root.is_dir():
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total_bytes += path.stat().st_size
                    file_count += 1
                    if path.parent == root:
                        top_level.add(path.name)
            except OSError:
                # 统计期间的删除/权限问题跳过单个文件，不失败整个指标
                continue
    referenced = {
        Path(p).name
        for p in session.exec(select(Attempt.audio_path)).all()  # type: ignore[arg-type]
    }
    result = {
        "root": str(root),
        "total_bytes": total_bytes,
        "file_count": file_count,
        "orphan_count": len(top_level - referenced),
        "approx": True,
    }
    with _audio_cache_lock:
        _audio_cache = result
        _audio_cached_at = now
    return result


def _scoring_queue_stats(session: Session) -> dict[str, Any]:
    rows = session.exec(
        select(Attempt.status, func.count()).group_by(Attempt.status)
    ).all()
    by_status = {
        status.value if hasattr(status, "value") else status: count
        for status, count in rows
    }
    # QUEUED 最老年龄：排了多久还没被评分线程领走（堆积告警的核心数）
    now = datetime.now(UTC)
    oldest_queued = session.exec(
        select(func.min(col(Attempt.created_at))).where(
            Attempt.status == AttemptStatus.QUEUED
        )
    ).one()
    oldest_queued_age_s = (
        (now - oldest_queued).total_seconds() if oldest_queued else None
    )
    return {
        "by_status": by_status,
        "oldest_queued_age_s": oldest_queued_age_s,
        "workers_configured": settings.SCORING_WORKERS,
        "executor_running": worker.executor_is_running(),
        # 三态：idle=池未创建（空闲正常态），stopped=终局关闭；红标只看 stopped
        "executor_state": worker.executor_state(),
    }


def _db_pool_stats() -> dict[str, Any]:
    """连接池实时水位：考试高峰是否打满在这里看，不改参数先看数。
    pool_size=10/max_overflow=20 是对齐 40 人齐交峰值的既定配置。

    capacity = pool_size + max_overflow（配置容量）。overflow() 是当前
    溢出计数：未溢出时为负值（冷启动 -pool_size），且溢出后与
    checked_out 同涨——不能当分母用。"""
    pool = _db.engine.pool
    return {
        "pool_size": pool.size(),
        "max_overflow": pool._max_overflow,  # noqa: SLF001 - 容量口径无公开 getter
        "capacity": pool.size() + pool._max_overflow,  # noqa: SLF001
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }


def collect_metrics(session: Session) -> dict[str, Any]:
    """实时指标快照（评分队列/引擎失败率/连接池/音频存储）。

    /admin/metrics 与大盘性能区共用一份口径；进程内计数器重启归零。
    """
    stats = call_stats()
    return {
        "process": PROCESS_INFO,
        "db_pool": _db_pool_stats(),
        "scoring": _scoring_queue_stats(session),
        "providers": {
            "asr": {
                "provider": settings.ASR_PROVIDER,
                **stats.get(
                    "asr",
                    {
                        "calls": 0,
                        "failures": 0,
                        "failure_rate": 0.0,
                        "avg_seconds": 0.0,
                    },
                ),
            },
            # llm 桶 = 全部 llm* 细分 kind（rubric 评分/出题/词汇讲解与学情）
            # 的聚合口径；by_kind 明细供成本归因
            "llm": {
                "model": settings.ARK_RUBRIC_MODEL,
                **call_stats_by_prefix("llm"),
                "by_kind": {k: v for k, v in stats.items() if k.startswith("llm")},
            },
            "tts": {
                "model": settings.ARK_TTS_MODEL,
                "voice": settings.ARK_TTS_VOICE,
                **stats.get(
                    "tts",
                    {
                        "calls": 0,
                        "failures": 0,
                        "failure_rate": 0.0,
                        "avg_seconds": 0.0,
                    },
                ),
            },
        },
        "audio_storage": _audio_storage_stats(session),
        "note": "进程内计数器，重启归零；趋势看增量",
    }


@router.get("")
def read_metrics(session: SessionDep, _superuser: SuperUserDep) -> Any:
    return collect_metrics(session)
