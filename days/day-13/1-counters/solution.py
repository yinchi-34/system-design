"""Day 13 · 分片计数器 + 缓冲聚合 + HyperLogLog。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
HyperLogLog 的哈希必须是：sha1(data) 前 8 字节按大端解释的 64 位整数。
"""

from __future__ import annotations

import hashlib  # noqa: F401
import math  # noqa: F401
import random
import threading  # noqa: F401
import time
from typing import Callable, Dict, Hashable, List, Optional, Union


class ShardedCounter:
    def __init__(self, num_shards: int, *, rng: Optional[random.Random] = None) -> None:
        raise NotImplementedError

    @property
    def num_shards(self) -> int:
        raise NotImplementedError

    def increment(self, key: Hashable, delta: int = 1) -> int:
        """用 rng.randrange(num_shards) 挑一个分片加上 delta，返回分片编号。"""
        raise NotImplementedError

    def get(self, key: Hashable) -> int:
        raise NotImplementedError

    def shards(self, key: Hashable) -> List[int]:
        raise NotImplementedError


class BufferedCounter:
    def __init__(
        self,
        sink: Callable[[Dict[Hashable, int]], None],
        *,
        flush_interval: float = 1.0,
        max_keys: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        raise NotImplementedError

    @property
    def failed_flushes(self) -> int:
        raise NotImplementedError

    def increment(self, key: Hashable, delta: int = 1) -> None:
        """累加到缓冲；到时间或 key 太多就 flush。永远不因 sink 出错而抛异常。"""
        raise NotImplementedError

    def flush(self) -> int:
        """一次性把缓冲交给 sink。失败时合并回缓冲、计数并重新抛出。"""
        raise NotImplementedError

    def pending(self, key: Hashable) -> int:
        raise NotImplementedError

    def close(self) -> int:
        raise NotImplementedError


class HyperLogLog:
    def __init__(self, p: int = 14) -> None:
        """p 取 4..16，寄存器个数 m = 2**p。"""
        raise NotImplementedError

    @property
    def registers(self) -> bytes:
        raise NotImplementedError

    def add(self, item: Union[str, bytes]) -> bool:
        """寄存器有变化返回 True。"""
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def merge(self, other: "HyperLogLog") -> "HyperLogLog":
        raise NotImplementedError
