"""Day 10 · Trie + Top-K（搜索联想的核心数据结构）。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
排序规则：次数从大到小，次数相同按字符串字典序从小到大。
"""

from __future__ import annotations

import heapq  # noqa: F401  提示：streaming_top_k 用大小为 k 的堆
import re  # noqa: F401
from typing import Iterable, List, Optional, Tuple


def normalize_query(q: str) -> str:
    """小写、去首尾空白、内部连续空白合并为一个空格。结果为空抛 ValueError。"""
    raise NotImplementedError


def normalize_prefix(p: str) -> str:
    """小写、去开头空白、内部连续空白合并为一个空格，末尾空白保留为一个空格。"""
    raise NotImplementedError


class AutocompleteTrie:
    def __init__(self, k: int = 5) -> None:
        """每个节点缓存子树里的 Top-K。"""
        raise NotImplementedError

    def add(self, query: str, count: int = 1) -> None:
        """次数加 count（>= 1 的整数），并更新路径上每个节点的 Top-K 缓存。"""
        raise NotImplementedError

    def remove(self, query: str) -> bool:
        """彻底删除这个词；路径上受影响的节点要重新计算 Top-K。"""
        raise NotImplementedError

    def frequency(self, query: str) -> int:
        raise NotImplementedError

    def suggest(self, prefix: str, limit: Optional[int] = None) -> List[str]:
        """直接返回前缀节点缓存里的前 limit 个词（limit 为 None 表示 k 个）。"""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def __contains__(self, query: str) -> bool:
        raise NotImplementedError


def streaming_top_k(pairs: Iterable[Tuple[str, int]], k: int) -> List[Tuple[str, int]]:
    """只遍历一次、只用 O(k) 额外内存，返回排好序的 Top-K。"""
    raise NotImplementedError
