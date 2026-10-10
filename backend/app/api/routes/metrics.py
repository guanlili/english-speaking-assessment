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
from app.core.config import settings
from app.core.metrics import call_stats
from app.models import Attempt, AttemptStatus
from app.scoring import worker

router = APIRouter(prefix="/admin/metrics", tags=["admin"])

_audio_cache_lock = threading.Lock()
_audio_cache: dict[str, Any] | None = None
_audio_cached_at = 0.0
_AUDIO_CACHE_TTL_S = 60.0


def _audio_storage_stats() -> dict[str, Any]:
    """统计音频目录（含 content/ 标准音）：总字节与文件数，60s 缓存。"""
    global _audio_cache, _audio_cached_at
    now = time.monotonic()
    with _audio_cache_lock:
        if _audio_cache is not None and now - _audio_cached_at < _AUDIO_CACHE_TTL_S:
            return _audio_cache
    root = Path(settings.AUDIO_STORAGE_DIR)
    total_bytes = 0
    file_count = 0
    if root.is_dir():
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    total_bytes += path.stat().st_size
                    file_count += 1
            except OSError:
                # 统计期间的删除/权限问题跳过单个文件，不失败整个指标
                continue
    result = {
        "root": str(root),
        "total_bytes": total_bytes,
        "file_count": file_count,
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
    }


@router.get("")
def read_metrics(session: SessionDep, _superuser: SuperUserDep) -> Any:
    return {
        "scoring": _scoring_queue_stats(session),
        "providers": {
            "asr": {
                "provider": settings.ASR_PROVIDER,
                **call_stats().get(
                    "asr",
                    {
                        "calls": 0,
                        "failures": 0,
                        "failure_rate": 0.0,
                        "avg_seconds": 0.0,
                    },
                ),
            },
            "llm": {
                "model": settings.ARK_RUBRIC_MODEL,
                **call_stats().get(
                    "llm",
                    {
                        "calls": 0,
                        "failures": 0,
                        "failure_rate": 0.0,
                        "avg_seconds": 0.0,
                    },
                ),
            },
        },
        "audio_storage": _audio_storage_stats(),
        "note": "进程内计数器，重启归零；趋势看增量",
    }
