"""Day 02 · 一致性哈希（虚拟节点 + 权重 + 副本）。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
"""

from __future__ import annotations

import bisect  # noqa: F401  提示：查找环上位置时会用到
import hashlib
from typing import Callable, Iterable, List, Optional, Set


def default_hash(s: str) -> int:
    """md5 前 8 字节，大端序转整数。已经写好，不用改。"""
    return int.from_bytes(hashlib.md5(s.encode("utf-8")).digest()[:8], "big")


class ConsistentHashRing:
    def __init__(
        self,
        nodes: Optional[Iterable[str]] = None,
        vnodes: int = 100,
        hash_fn: Callable[[str], int] = default_hash,
    ) -> None:
        raise NotImplementedError

    def add_node(self, node: str, weight: float = 1.0) -> None:
        """加入物理节点，在环上放 max(1, round(vnodes * weight)) 个虚拟节点。"""
        raise NotImplementedError

    def remove_node(self, node: str) -> None:
        """删除物理节点及其所有虚拟节点。不存在时抛 KeyError。"""
        raise NotImplementedError

    def get_node(self, key: str) -> str:
        """返回 key 顺时针遇到的第一个虚拟节点所属的物理节点。O(log V)。"""
        raise NotImplementedError

    def get_nodes(self, key: str, n: int) -> List[str]:
        """从 key 的位置顺时针收集 n 个不重复的物理节点。"""
        raise NotImplementedError

    @property
    def nodes(self) -> Set[str]:
        """当前所有物理节点（副本）。"""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def __contains__(self, node: object) -> bool:
        raise NotImplementedError
