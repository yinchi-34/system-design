"""Day 06 · Snowflake ID 生成器 + 号段分配器。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
Snowflake 里所有取时间的地方都调用 self 上保存的 clock，不要直接调 time.time()。
"""

from __future__ import annotations

import math  # noqa: F401
import threading  # noqa: F401  提示：两个类都要线程安全
import time  # noqa: F401
from typing import Callable, NamedTuple, Optional

DEFAULT_EPOCH_MS = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC

TIMESTAMP_BITS = 41
DATACENTER_BITS = 5
WORKER_BITS = 5
SEQUENCE_BITS = 12


class ClockMovedBackwardsError(RuntimeError):
    """时钟回拨超过允许的幅度，拒绝发号。"""


class SnowflakeParts(NamedTuple):
    timestamp_ms: int  # 绝对 Unix 毫秒（已加回纪元）
    datacenter_id: int
    worker_id: int
    sequence: int


class Snowflake:
    def __init__(
        self,
        worker_id: int,
        datacenter_id: int = 0,
        *,
        epoch_ms: int = DEFAULT_EPOCH_MS,
        clock: Optional[Callable[[], int]] = None,
        max_backward_ms: int = 5,
    ) -> None:
        """worker_id / datacenter_id 取值 0..31；clock() 返回当前 Unix 毫秒。"""
        raise NotImplementedError

    def next_id(self) -> int:
        raise NotImplementedError


def parse_id(snowflake_id: int, epoch_ms: int = DEFAULT_EPOCH_MS) -> SnowflakeParts:
    """把 ID 拆回各个字段。"""
    raise NotImplementedError


class SegmentAllocator:
    def __init__(
        self,
        fetch_segment: Callable[[int], int],
        step: int,
        *,
        prefetch_at: float = 0.9,
    ) -> None:
        """fetch_segment(step) 返回新号段的起点 start，号段为 [start, start + step)。构造时就取第一段。"""
        raise NotImplementedError

    @property
    def fetch_count(self) -> int:
        """成功调用 fetch_segment 的次数（含构造时那次）。"""
        raise NotImplementedError

    def next_id(self) -> int:
        raise NotImplementedError
