"""进程内滑动窗口限流：IP / 账号双桶（从 login.py 泛化，2026-10-08）。

单机内存字典 + 线程锁：多 worker 部署时各进程独立，实际限额按 worker
数放大——定位是纵深防御（挡爆破/刷接口），不追求精确配额。窗口过期
条目惰性清理；键空间超阈值时主动修剪（防随机伪造键名膨胀内存）。
"""

import time
from threading import Lock

from fastapi import HTTPException

_KEYS_PRUNE_THRESHOLD = 4096


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit = limit
        self.window_s = window_s
        self._attempts: dict[str, list[float]] = {}
        self._lock = Lock()

    def check(self, bucket: str, *, detail: str = "请求过于频繁，请稍后再试") -> None:
        """超限抛 429；未超限计入窗口。detail 是稳定标识（调用方自定义文案）。"""
        now = time.monotonic()
        with self._lock:
            if len(self._attempts) > _KEYS_PRUNE_THRESHOLD:
                cutoff = now - self.window_s
                for key in [
                    k
                    for k, window in self._attempts.items()
                    if not window or window[-1] < cutoff
                ]:
                    self._attempts.pop(key, None)
            window = self._attempts.get(bucket, [])
            cutoff = now - self.window_s
            while window and window[0] < cutoff:
                window.pop(0)
            if len(window) >= self.limit:
                raise HTTPException(
                    status_code=429,
                    detail=detail,
                    headers={"Retry-After": str(self.window_s)},
                )
            window.append(now)
            self._attempts[bucket] = window

    def record_success(self, bucket: str, *, refund_only: bool = False) -> None:
        """成功后清桶（失败计数不累积误伤正常用户）。

        refund_only：只退还本次成功在 check 里占用的额度，保留窗口内的
        失败计数——共享桶（如 NAT 出口的 IP 桶）用：持任一有效账号的
        攻击者交替「失败喷洒 + 成功登录自己」时，成功不能再抹掉同桶的
        攻击痕迹；否则每轮成功清一次桶，横向喷洒永不触顶。独立桶
        （账号桶：成功即证明本人）维持整桶清空。
        """
        with self._lock:
            if not refund_only:
                self._attempts.pop(bucket, None)
                return
            window = self._attempts.get(bucket)
            if window:
                window.pop()
                if not window:
                    self._attempts.pop(bucket, None)
