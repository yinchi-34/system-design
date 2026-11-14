"""Day 11 · 熔断器 + 指数退避重试 + 重试预算。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
时间一律通过注入的 clock() 取，等待一律通过注入的 sleep() 完成。
"""

from __future__ import annotations

import random  # noqa: F401
import threading  # noqa: F401
import time
from collections import deque  # noqa: F401  提示：重试预算的滑动窗口
from typing import Any, Callable, Optional, Tuple, Type

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """熔断器打开（或试探名额已满），没有调用下游。"""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"circuit open, retry after {retry_after:.3f}s")
        self.retry_after = retry_after


def compute_backoff(
    attempt: int,
    *,
    base: float,
    cap: float,
    jitter: str = "full",
    rng: Optional[random.Random] = None,
) -> float:
    """第 attempt 次失败后（从 1 开始）要等待的秒数。jitter: "none" / "full" / "equal"。"""
    raise NotImplementedError


class RetryBudget:
    def __init__(
        self,
        *,
        ratio: float = 0.1,
        min_retries: int = 10,
        window: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        raise NotImplementedError

    def record_request(self) -> None:
        """记录一次原始请求（不含重试）。"""
        raise NotImplementedError

    def try_acquire_retry(self) -> bool:
        """窗口内重试数 < max(min_retries, ratio × 窗口内请求数) 时记一次重试并返回 True。"""
        raise NotImplementedError


def retry(
    func: Callable[[], Any],
    *,
    max_attempts: int = 3,
    base: float = 0.1,
    cap: float = 10.0,
    jitter: str = "full",
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    rng: Optional[random.Random] = None,
    budget: Optional[RetryBudget] = None,
) -> Any:
    raise NotImplementedError


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        failure_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
        clock: Callable[[], float] = time.monotonic,
        on_state_change: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        raise NotImplementedError

    @property
    def state(self) -> str:
        """CLOSED / OPEN / HALF_OPEN（先做惰性的时间转换）。"""
        raise NotImplementedError

    @property
    def failure_count(self) -> int:
        """CLOSED 状态下当前的连续失败次数。"""
        raise NotImplementedError

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """不要在持有锁的时候调用 func。"""
        raise NotImplementedError

    def reset(self) -> None:
        """人工强制合闸。"""
        raise NotImplementedError
