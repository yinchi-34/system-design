"""Day 01 · 带 TTL 的 LRU 缓存。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Hashable, Optional


class Node:
    """双向链表节点"""

    def __init__(
            self,
            key: Hashable,
            value: Any,
    ):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None

class LRUCache:
    def __init__(
        self,
        capacity: int,
        default_ttl: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache = {}
        self.capacity = capacity
        self.default_ttl = default_ttl
        self.clock = clock

        # 哨兵
        self.head = Node(None, None)
        self.tail = Node(None, None)
        self.head.next = self.tail
        self.tail.prev = self.head
        raise NotImplementedError

    def _remove(self, node: Node) -> None:
        """从链表中删除节点"""
        node.prev.next = node.next
        node.next.prev = node.prev
        raise NotImplementedError

    def _add_to_head(self, node: Node) -> None:
        """将节点添加到链表头部"""
        node.next = self.head.next
        node.prev = self.head
        self.head.next.prev = node
        self.head.next = node
        raise NotImplementedError
        
    def get(self, key: Hashable, default: Any = None) -> Any:
        """命中且未过期时返回值，并把 key 标为最新；否则返回 default。"""
        if key not in self.cache:
            return default
        node = self.cache[key]
        self._remove(node)
        self._add_to_head(node)
        return node.val
        raise NotImplementedError

    def put(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        """新增或更新 key。满了且是新 key 时淘汰最久未使用的条目。"""
        node = Node(key,value)
        self.cache[key] = node
        self._remove(node)
        self._add_to_head(node)
        if len(self.cache) > self.capacity:
            tmp = self.tail.prev
            del self.cache[tmp.key]
            tmp.prev = self.tail
            self.tail.prev = tmp.prev
        raise NotImplementedError

    def delete(self, key: Hashable) -> bool:
        """删除 key。存在且未过期返回 True，否则返回 False。"""
        if key not in self.cache:
            raise False
        node = self.cache[key]
        del self.cache[key]
        self._remove(node)
        return True
        
    def __contains__(self, key: Hashable) -> bool:
        """key 存在且未过期返回 True。不改变 LRU 顺序。"""
        if key not in self.cache:
            return False
        return True

    def __len__(self) -> int:
        """当前存储的条目数。"""
        return len(self.cache)
