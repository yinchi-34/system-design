"""Day 12 · 带租约的分布式锁 + fencing token。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
时间一律通过注入的 clock() 取，不要开后台线程。
"""

from __future__ import annotations

import contextlib  # noqa: F401  提示：contextlib.contextmanager
import threading  # noqa: F401
import time
from typing import Any, Callable, Iterator, NamedTuple, Optional


class StaleTokenError(RuntimeError):
    """写入时带的令牌号比存储见过的最大令牌号小。"""


class LockNotAcquiredError(RuntimeError):
    """lock() 上下文管理器没拿到锁。"""


class LockNotHeldError(RuntimeError):
    """客户端认为自己没有持有这把锁。"""


class Lease(NamedTuple):
    name: str
    owner: str
    token: int  # 每个锁名单调递增，从 1 开始
    expires_at: float  # 服务端时钟


class LockServer:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        raise NotImplementedError

    def acquire(self, name: str, owner: str, ttl: float) -> Optional[Lease]:
        """锁空闲时发新租约（token = 该锁名计数器 + 1），否则返回 None。不可重入。"""
        raise NotImplementedError

    def renew(self, name: str, owner: str, token: int, ttl: float) -> bool:
        raise NotImplementedError

    def release(self, name: str, owner: str, token: int) -> bool:
        raise NotImplementedError

    def holder(self, name: str) -> Optional[Lease]:
        raise NotImplementedError


class FencedStorage:
    def __init__(self) -> None:
        raise NotImplementedError

    @property
    def max_token(self) -> int:
        raise NotImplementedError

    def write(self, key: str, value: Any, token: int) -> None:
        """token 小于见过的最大令牌号时抛 StaleTokenError，不写入。"""
        raise NotImplementedError

    def read(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError


class LockClient:
    def __init__(
        self,
        server: LockServer,
        owner: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        drift_factor: float = 0.01,
    ) -> None:
        raise NotImplementedError

    def acquire(self, name: str, ttl: float) -> bool:
        """本地有效期截止 = 发请求前的 start + ttl - ttl * drift_factor。"""
        raise NotImplementedError

    def is_held(self, name: str) -> bool:
        """只看本地时钟和本地截止时间，不问服务端。"""
        raise NotImplementedError

    def token(self, name: str) -> int:
        raise NotImplementedError

    def renew(self, name: str) -> bool:
        raise NotImplementedError

    def release(self, name: str) -> bool:
        raise NotImplementedError

    def lock(self, name: str, ttl: float) -> "contextlib.AbstractContextManager[int]":
        """拿不到抛 LockNotAcquiredError；拿到了 yield 令牌号，退出时释放。"""
        raise NotImplementedError
