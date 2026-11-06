"""Day 03 · 限流器（令牌桶 + 滑动窗口日志 + 滑动窗口计数）。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
时间一律通过 self.clock() 取，不要直接调 time.time() / time.monotonic()。
"""

from __future__ import annotations

import time
from collections import deque  # noqa: F401  提示：滑动窗口日志会用到
from typing import Callable


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """capacity：桶的容量（允许的突发量）；refill_rate：每秒补充的令牌数。初始是满桶。"""
        raise NotImplementedError

    @property
    def tokens(self) -> float:
        """当前桶里的令牌数（先按流逝的时间补充）。"""
        raise NotImplementedError

    def allow(self, cost: float = 1) -> bool:
        """令牌够 cost 个就扣掉并返回 True；不够返回 False，且不扣任何令牌。"""
        raise NotImplementedError

    def retry_after(self, cost: float = 1) -> float:
        """还要等多少秒才能有 cost 个令牌，现在就够返回 0。不扣令牌。"""
        raise NotImplementedError


class SlidingWindowLog:
    def __init__(
        self,
        limit: int,
        window: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """任意长度为 window 秒的窗口 (now - window, now] 内，最多放行 limit 个请求。"""
        raise NotImplementedError

    def allow(self) -> bool:
        raise NotImplementedError

    def retry_after(self) -> float:
        """还要等多少秒才能放行下一个请求，现在就能放行返回 0。"""
        raise NotImplementedError

    def __len__(self) -> int:
        """当前窗口内已放行的请求数。"""
        raise NotImplementedError


class SlidingWindowCounter:
    def __init__(
        self,
        limit: int,
        window: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """用「上一个固定窗口 + 当前固定窗口」两个计数器近似滑动窗口。"""
        raise NotImplementedError

    def estimated_count(self) -> float:
        """上一窗口计数 × (1 - 当前窗口已过去的比例) + 当前窗口计数。"""
        raise NotImplementedError

    def allow(self) -> bool:
        """estimated_count() + 1 <= limit 时放行并计数，否则拒绝（拒绝的不计数）。"""
        raise NotImplementedError
