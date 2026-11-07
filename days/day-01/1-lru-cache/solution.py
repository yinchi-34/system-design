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
            expire:Optional[float],
    ):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None
        self.expire = expire


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
        self.head = Node(None, None, None)
        self.tail = Node(None, None, None)
        self.head.next = self.tail
        self.tail.prev = self.head

        if self.capacity < 1 :
            raise ValueError("Capacity must be >= 1")

        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("default_ttl must be > 0")

    def _remove(self, node: Node) -> None:
        """从链表中删除节点"""
        node.prev.next = node.next
        node.next.prev = node.prev

    def _add_to_head(self, node: Node) -> None:
        """将节点添加到链表头部"""
        node.next = self.head.next
        node.prev = self.head
        self.head.next.prev = node
        self.head.next = node

    def _get_live_node(self, node: Node) -> bool:
        if node.expire is None or node.expire > self.clock():
            return True
        return False
        
    def get(self, key: Hashable, default: Any = None) -> Any:
        """命中且未过期时返回值，并把 key 标为最新；否则返回 default。"""
        if key not in self.cache or not self._get_live_node(self.cache[key]):
            return default
        node = self.cache[key]
        self._remove(node)
        self._add_to_head(node)
        return node.value

    def put(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        """新增或更新 key。满了且是新 key 时淘汰最久未使用的条目。"""
        effective_ttl = self.default_ttl if ttl is None else ttl
        if effective_ttl is not None and effective_ttl <= 0:
            raise ValueError("ttl must be > 0")
        expire = (
            None
            if effective_ttl is None
            else self.clock() + effective_ttl
        )
        
        if key not in self.cache:
            node = Node(key=key, value=value, expire=expire)
            self.cache[key] = node
        else:
            node = self.cache[key]
            self._remove(node=node)
            node.value = value
            node.expire = expire
        
        self._add_to_head(node)
        
        if len(self.cache) > self.capacity:
            tmp = self.tail.prev
            del self.cache[tmp.key]
            self._remove(tmp)

    def delete(self, key: Hashable) -> bool:
        """删除 key。存在且未过期返回 True，否则返回 False。"""
        if key not in self.cache or not self._get_live_node(self.cache[key]):
            return False
        node = self.cache[key]
        del self.cache[key]
        self._remove(node)
        return True
        
    def __contains__(self, key: Hashable) -> bool:
        """key 存在且未过期返回 True。不改变 LRU 顺序。"""
        return key in self.cache and self._get_live_node(self.cache[key])

    def __len__(self) -> int:
        """当前存储的条目数。"""
        return len(self.cache)