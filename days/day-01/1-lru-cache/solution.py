"""Day 01 · 带 TTL 的 LRU 缓存。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Hashable, Optional


class LRUCache:
    def __init__(
        self,
        capacity: int,
        default_ttl: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        raise NotImplementedError

    def get(self, key: Hashable, default: Any = None) -> Any:
        """命中且未过期时返回值，并把 key 标为最新；否则返回 default。"""
        raise NotImplementedError

    def put(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        """新增或更新 key。满了且是新 key 时淘汰最久未使用的条目。"""
        raise NotImplementedError

    def delete(self, key: Hashable) -> bool:
        """删除 key。存在且未过期返回 True，否则返回 False。"""
        raise NotImplementedError

    def __contains__(self, key: Hashable) -> bool:
        """key 存在且未过期返回 True。不改变 LRU 顺序。"""
        raise NotImplementedError

    def __len__(self) -> int:
        """当前存储的条目数。"""
        raise NotImplementedError
