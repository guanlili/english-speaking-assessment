"""进程内运维计数器：ASR/LLM 调用次数、失败与耗时。

设计边界（不引 Prometheus，先解决「出问题只能翻日志」）：
- 计数器在进程内存里，重启归零——趋势看增量，不看绝对存量；
- 只在统一出口埋点：LLM=ArkChatClient.chat、ASR=worker 的 provider.transcribe
  调用处（所有 provider 都经过）；
- 线程安全（评分线程池并发调用），开销为一次锁内 dict 自增。
"""

import logging
import threading

from app.core.request_context import PROCESS_INFO, request_id

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# kind -> {"calls": int, "failures": int, "total_seconds": float}
_stats: dict[str, dict[str, float]] = {}
# LLM kind -> {"in": prompt_tokens, "out": completion_tokens}（费用记账；
# 与 call 计数同锁同生命周期，日快照线程取当日增量）
_llm_tokens: dict[str, dict[str, int]] = {}


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
    logger.info(
        "provider_call request_id=%s instance_id=%s kind=%s ok=%s duration_s=%.3f",
        request_id.get(),
        PROCESS_INFO["instance_id"],
        kind,
        ok,
        max(0.0, duration_s),
    )


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


def call_stats_by_prefix(prefix: str) -> dict[str, float]:
    """前缀聚合的单条快照："llm" → llm / llm_rubric / llm_vocab_* 合计。

    调用被拆成细分 kind 归因成本后，总量口径仍要一个入口（llm 整体
    失败率）；空集返回零值，字段形状与 call_stats 一致。"""
    with _lock:
        calls = failures = total_seconds = 0.0
        for kind, entry in _stats.items():
            if kind == prefix or kind.startswith(f"{prefix}_"):
                calls += entry["calls"]
                failures += entry["failures"]
                total_seconds += entry["total_seconds"]
        return {
            "calls": calls,
            "failures": failures,
            "failure_rate": failures / calls if calls else 0.0,
            "avg_seconds": total_seconds / calls if calls else 0.0,
        }


def record_llm_tokens(kind: str, *, prompt_tokens: int, completion_tokens: int) -> None:
    """记一次 LLM 调用的真实 token 用量（Ark 响应 usage 字段）。

    与 record_call 分开：token 只有成功响应才有，且计费口径独立。
    """
    with _lock:
        entry = _llm_tokens.setdefault(kind, {"in": 0, "out": 0})
        entry["in"] += max(0, prompt_tokens)
        entry["out"] += max(0, completion_tokens)


def llm_token_stats() -> dict[str, dict[str, int]]:
    """快照：各 LLM kind 的累计 prompt/completion tokens（重启归零）。"""
    with _lock:
        return {kind: dict(entry) for kind, entry in _llm_tokens.items()}


def reset_for_tests() -> None:
    with _lock:
        _stats.clear()
        _llm_tokens.clear()
