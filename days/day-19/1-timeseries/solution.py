"""Day 19 · 时间序列：降采样、计数器速率、分级存储、告警规则。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
时间戳一律是整数秒。时间一律通过注入的 clock() 取。
"""

from __future__ import annotations

import time
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple, Union

Number = Union[int, float]
Point = Tuple[int, Number]

AGGS = ("avg", "sum", "min", "max", "count")


class Agg(NamedTuple):
    """一个时间桶的聚合结果。只存这四个数，就能算出 AGGS 里所有的聚合。"""

    count: int
    sum: float
    min: float
    max: float

    @classmethod
    def of(cls, v: Number) -> "Agg":
        raise NotImplementedError

    def merge(self, other: "Agg") -> "Agg":
        raise NotImplementedError

    def value(self, agg: str) -> Number:
        raise NotImplementedError


def downsample(points: Iterable[Point], step: int, agg: str = "avg") -> List[Tuple[int, Number]]:
    raise NotImplementedError


def counter_increase(points: Iterable[Point]) -> Optional[Number]:
    raise NotImplementedError


def counter_rate(points: Iterable[Point]) -> Optional[float]:
    raise NotImplementedError


class TimeSeriesDB:
    def __init__(
        self,
        *,
        raw_retention: int = 3600,
        rollup_step: int = 60,
        rollup_retention: int = 30 * 86400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        raise NotImplementedError

    def add(self, series: str, ts: int, value: Number) -> None:
        raise NotImplementedError

    def compact(self) -> int:
        raise NotImplementedError

    def raw_count(self) -> int:
        raise NotImplementedError

    def rollup_count(self) -> int:
        raise NotImplementedError

    def series(self) -> List[str]:
        raise NotImplementedError

    def raw_points(self, series: str, start: int, end: int) -> List[Point]:
        raise NotImplementedError

    def query(self, series: str, start: int, end: int, step: int, agg: str = "avg") -> List[Tuple[int, Number]]:
        raise NotImplementedError


class AlertRule:
    def __init__(self, name: str, op: str, threshold: Number, *, for_seconds: int = 0) -> None:
        """公开属性：name、op、threshold、for_seconds、state、since、events。"""
        raise NotImplementedError

    def evaluate(self, ts: int, value: Optional[Number]) -> str:
        raise NotImplementedError
