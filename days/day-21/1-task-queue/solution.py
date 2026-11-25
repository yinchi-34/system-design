"""Day 21 · 延迟队列 + 优先级调度 + 租约 + 退避重试。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
时间一律通过注入的 clock() 取。
"""

from __future__ import annotations

import heapq  # noqa: F401
import itertools  # noqa: F401
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional


class Lease(NamedTuple):
    task_id: str
    payload: Any
    attempt: int  # 这是第几次执行，从 1 开始
    token: int    # 这次租约的令牌，全局递增


class TaskScheduler:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        lease_seconds: float = 30.0,
        max_attempts: int = 3,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
    ) -> None:
        raise NotImplementedError

    def backoff(self, attempt: int) -> float:
        raise NotImplementedError

    def submit(self, task_id: str, payload: Any = None, *, run_at: Optional[float] = None, priority: int = 0) -> bool:
        raise NotImplementedError

    def poll(self, n: int = 1) -> List[Lease]:
        raise NotImplementedError

    def ack(self, task_id: str, token: int) -> bool:
        raise NotImplementedError

    def fail(self, task_id: str, token: int, *, retry: bool = True) -> bool:
        raise NotImplementedError

    def heartbeat(self, task_id: str, token: int) -> bool:
        raise NotImplementedError

    def cancel(self, task_id: str) -> bool:
        raise NotImplementedError

    def state(self, task_id: str) -> str:
        raise NotImplementedError

    def attempts(self, task_id: str) -> int:
        raise NotImplementedError

    def next_wakeup(self) -> Optional[float]:
        raise NotImplementedError

    def counts(self) -> Dict[str, int]:
        raise NotImplementedError
