"""Day 09 · Quorum 读写模拟（N/W/R、向量时钟、读修复）。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
没有真正的网络：W 个节点同步写入，其余在线副本的写放进待投递列表，由 deliver_pending() 投递。
"""

from __future__ import annotations

import hashlib  # noqa: F401  提示：rendezvous 哈希用 sha256
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class QuorumError(RuntimeError):
    """在线副本不足 W（写）或 R（读）。"""


class VectorClock:
    def __init__(self, counts: Optional[Mapping[str, int]] = None) -> None:
        """计数必须是非负整数；为 0 的项等同于不存在。"""
        raise NotImplementedError

    def get(self, node: str) -> int:
        raise NotImplementedError

    def increment(self, node: str) -> "VectorClock":
        raise NotImplementedError

    def merge(self, other: "VectorClock") -> "VectorClock":
        raise NotImplementedError

    def descends(self, other: "VectorClock") -> bool:
        """自己的每一项都 >= other。"""
        raise NotImplementedError

    def compare(self, other: "VectorClock") -> str:
        """"equal" / "before" / "after" / "concurrent"。"""
        raise NotImplementedError

    def to_dict(self) -> Dict[str, int]:
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError


Sibling = Tuple[Any, VectorClock]


class QuorumStore:
    def __init__(self, nodes: Sequence[str], n: int = 3, w: int = 2, r: int = 2) -> None:
        raise NotImplementedError

    def preference_list(self, key: str) -> List[str]:
        """rendezvous 哈希：按 sha256(f"{key}|{node}") 前 8 字节（大端整数）从大到小，取前 n 个。"""
        raise NotImplementedError

    def set_down(self, node: str) -> None:
        raise NotImplementedError

    def set_up(self, node: str) -> None:
        raise NotImplementedError

    def replica(self, node: str, key: str) -> List[Sibling]:
        """某个节点上这个 key 的兄弟版本（不管节点是否在线）。"""
        raise NotImplementedError

    @property
    def read_repairs(self) -> int:
        """累计读修复过的副本个数。"""
        raise NotImplementedError

    def put(
        self,
        key: str,
        value: Any,
        context: Optional[VectorClock] = None,
        *,
        coordinator: Optional[str] = None,
    ) -> VectorClock:
        raise NotImplementedError

    def deliver_pending(self) -> int:
        raise NotImplementedError

    def get(self, key: str) -> Tuple[List[Any], VectorClock]:
        raise NotImplementedError
