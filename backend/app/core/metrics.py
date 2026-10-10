"""进程内运维计数器：ASR/LLM 调用次数、失败与耗时。

设计边界（不引 Prometheus，先解决「出问题只能翻日志」）：
- 计数器在进程内存里，重启归零——趋势看增量，不看绝对存量；
- 只在统一出口埋点：LLM=ArkChatClient.chat、ASR=worker 的 provider.transcribe
  调用处（所有 provider 都经过）；
- 线程安全（评分线程池并发调用），开销为一次锁内 dict 自增。
"""

import threading

_lock = threading.Lock()
# kind -> {"calls": int, "failures": int, "total_seconds": float}
_stats: dict[str, dict[str, float]] = {}


def record_call(kind: str, *, ok: bool, duration_s: float) -> None:
    """记一次外部调用。kind 如 "asr" / "llm"；duration_s 为耗时秒。"""
    with _lock:
        entry = _stats.setdefault(
            kind, {"calls": 0.0, "failures": 0.0, "total_seconds": 0.0}
        )
        entry["calls"] += 1
        if not ok:
            entry["failures"] += 1
        entry["total_seconds"] += max(0.0, duration_s)


def call_stats() -> dict[str, dict[str, float]]:
    """快照：各 kind 的调用数/失败数/失败率/平均耗时。"""
    with _lock:
        snapshot: dict[str, dict[str, float]] = {}
        for kind, entry in _stats.items():
            calls = entry["calls"]
            snapshot[kind] = {
                "calls": calls,
                "failures": entry["failures"],
                "failure_rate": entry["failures"] / calls if calls else 0.0,
                "avg_seconds": (entry["total_seconds"] / calls if calls else 0.0),
            }
        return snapshot


def reset_for_tests() -> None:
    with _lock:
        _stats.clear()
