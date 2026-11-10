"""Day 07 · 内存版发布/订阅消息队列（ack、重投、死信）。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
时间一律通过 self 上保存的 clock() 取。不要开后台线程或定时器，超时都惰性处理。
"""

from __future__ import annotations

import heapq  # noqa: F401  提示：按发布顺序 / 按时间取最小值时可能用得上
import itertools  # noqa: F401
import threading  # noqa: F401
import time
import uuid  # noqa: F401
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class Message:
    message_id: str
    payload: Any
    delivery_count: int  # 第几次投递，第一次是 1
    receipt: Optional[str]  # 本次投递的回执；死信里为 None


class Broker:
    def __init__(
        self,
        *,
        ack_timeout: float = 30.0,
        max_deliveries: int = 5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        raise NotImplementedError

    # ---------- topic 与订阅 ----------

    def create_topic(self, topic: str) -> None:
        raise NotImplementedError

    def subscribe(self, topic: str, group: str) -> None:
        """只收到订阅之后发布的消息。重复订阅什么都不做。"""
        raise NotImplementedError

    def publish(self, topic: str, payload: Any) -> str:
        """给每个已订阅的组各放一份，返回 message_id。"""
        raise NotImplementedError

    # ---------- 消费 ----------

    def poll(self, topic: str, group: str, max_messages: int = 1) -> List[Message]:
        """按发布顺序返回最多 max_messages 条当前可见的消息，并把它们标记为 in-flight。"""
        raise NotImplementedError

    def ack(self, topic: str, group: str, receipt: str) -> bool:
        raise NotImplementedError

    def nack(self, topic: str, group: str, receipt: str, delay: float = 0.0) -> bool:
        raise NotImplementedError

    def extend(self, topic: str, group: str, receipt: str, seconds: float) -> bool:
        """把截止时间改成 现在 + seconds。"""
        raise NotImplementedError

    # ---------- 死信与运维 ----------

    def dead_letters(self, topic: str, group: str) -> List[Message]:
        raise NotImplementedError

    def redrive(self, topic: str, group: str) -> int:
        """把死信全部放回可见队列，delivery_count 清零，返回条数。"""
        raise NotImplementedError

    def stats(self, topic: str, group: str) -> Dict[str, int]:
        """{"ready": ..., "in_flight": ..., "delayed": ..., "dead": ...}"""
        raise NotImplementedError
