"""Day 08 · 主从复制模拟（异步复制、复制延迟、故障切换）。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
时间一律通过 self 上保存的 clock() 取。没有真正的网络和线程，复制只在 sync() / 半同步写时发生。
"""

from __future__ import annotations

import time
from typing import Any, Callable, List, NamedTuple, Optional, Sequence


class NodeDownError(RuntimeError):
    """节点宕机，不能读写或同步。"""


class NotEnoughReplicasError(RuntimeError):
    """半同步写时在线的 follower 不够。"""


class LogEntry(NamedTuple):
    term: int
    lsn: int  # 从 1 开始，等于它在日志里的位置
    key: str
    value: Any
    timestamp: float  # leader 写入时 clock() 的值


class ReplicatedStore:
    def __init__(self, nodes: Sequence[str], *, clock: Callable[[], float] = time.monotonic) -> None:
        """nodes[0] 是初始 leader，初始 term = 1。"""
        raise NotImplementedError

    @property
    def leader(self) -> str:
        raise NotImplementedError

    @property
    def term(self) -> int:
        raise NotImplementedError

    def followers(self) -> List[str]:
        """除 leader 外的节点，按构造顺序。"""
        raise NotImplementedError

    # ---------- 读写与复制 ----------

    def write(self, key: str, value: Any, *, sync_replicas: int = 0) -> int:
        """写 leader，返回 lsn。sync_replicas=k 时同步前 k 个在线 follower 后再返回。"""
        raise NotImplementedError

    def sync(self, node: str, max_entries: Optional[int] = None) -> int:
        """follower 从 leader 拉取日志（必要时先截断分叉部分），返回本次应用的条数。"""
        raise NotImplementedError

    def read(self, node: str, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def applied_lsn(self, node: str) -> int:
        raise NotImplementedError

    def log(self, node: str) -> List[LogEntry]:
        """返回该节点日志的副本。"""
        raise NotImplementedError

    # ---------- 复制延迟 ----------

    def lag(self, node: str) -> int:
        raise NotImplementedError

    def lag_seconds(self, node: str) -> float:
        raise NotImplementedError

    # ---------- 故障 ----------

    def set_down(self, node: str) -> None:
        raise NotImplementedError

    def set_up(self, node: str) -> None:
        raise NotImplementedError

    def failover(self) -> int:
        """leader 必须已宕机。提升最新的在线 follower，term + 1，返回丢失的写的条数。"""
        raise NotImplementedError

    def session(self) -> "Session":
        return Session(self)


class Session:
    """一个用户的会话：保证读自己的写 + 单调读。"""

    def __init__(self, store: ReplicatedStore) -> None:
        raise NotImplementedError

    @property
    def last_node(self) -> Optional[str]:
        """上一次 read 用的节点。"""
        raise NotImplementedError

    def write(self, key: str, value: Any, **kwargs: Any) -> int:
        raise NotImplementedError

    def read(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError
