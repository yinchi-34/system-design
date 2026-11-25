"""Day 22 · Gossip 成员协议：心跳计数器 + 故障检测 + 集群模拟。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
随机数一律用传进来的 rng（random.Random），时间一律用传进来的 clock()。
"""

from __future__ import annotations

import random
from typing import Callable, Dict, Iterable, List, Optional


class GossipNode:
    def __init__(
        self,
        node_id: str,
        *,
        clock: Callable[[], float],
        fail_timeout: float,
        cleanup_timeout: float,
        rng: Optional[random.Random] = None,
    ) -> None:
        raise NotImplementedError

    @property
    def heartbeat(self) -> int:
        raise NotImplementedError

    def tick(self) -> None:
        raise NotImplementedError

    def digest(self) -> Dict[str, int]:
        raise NotImplementedError

    def merge(self, digest: Dict[str, int]) -> int:
        raise NotImplementedError

    def status(self, node_id: str) -> Optional[str]:
        raise NotImplementedError

    def alive_members(self) -> List[str]:
        raise NotImplementedError

    def dead_members(self) -> List[str]:
        raise NotImplementedError

    def pick_peers(self, k: int) -> List[str]:
        raise NotImplementedError


class GossipCluster:
    def __init__(
        self,
        n: int,
        *,
        fanout: int = 2,
        fail_timeout: float = 10,
        cleanup_timeout: float = 20,
        drop_rate: float = 0.0,
        seed: int = 0,
    ) -> None:
        """公开属性：time、ids、nodes、down、messages。"""
        raise NotImplementedError

    def reachable(self, a: str, b: str) -> bool:
        raise NotImplementedError

    def step(self) -> None:
        raise NotImplementedError

    def kill(self, node_id: str) -> None:
        raise NotImplementedError

    def partition(self, *groups: Iterable[str]) -> None:
        raise NotImplementedError

    def heal(self) -> None:
        raise NotImplementedError

    def converged(self) -> bool:
        raise NotImplementedError

    def run_until(self, pred: Callable[[], bool], max_rounds: int) -> Optional[int]:
        raise NotImplementedError
