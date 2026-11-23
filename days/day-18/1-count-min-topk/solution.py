"""Day 18 · Count-Min Sketch + 热点 Top-K + 滑动窗口热搜。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
行哈希已经写好（row_index），必须用它，测试会检查计数表的内容。
时间一律通过注入的 clock() 取。
"""

from __future__ import annotations

import hashlib
import math  # noqa: F401
import time
from typing import Callable, Dict, List, Optional, Set, Tuple, Union

Item = Union[str, bytes]


def _data(item: Item) -> bytes:
    if isinstance(item, str):
        return item.encode("utf-8")
    if isinstance(item, bytes):
        return item
    raise TypeError(f"unsupported item type: {type(item).__name__}")


def row_index(item: Item, row: int, width: int) -> int:
    """第 row 行里，item 落在哪一列。"""
    d = hashlib.sha256(row.to_bytes(4, "big") + _data(item)).digest()
    return int.from_bytes(d[:8], "big") % width


class CountMinSketch:
    def __init__(self, width: int, depth: int, *, conservative: bool = False) -> None:
        """公开属性：width、depth、conservative、total。"""
        raise NotImplementedError

    @classmethod
    def from_error(cls, epsilon: float, delta: float, *, conservative: bool = False) -> "CountMinSketch":
        raise NotImplementedError

    def add(self, item: Item, count: int = 1) -> int:
        """加上 count，返回加完以后 item 的估计值。"""
        raise NotImplementedError

    def estimate(self, item: Item) -> int:
        raise NotImplementedError

    def merge(self, other: "CountMinSketch") -> "CountMinSketch":
        raise NotImplementedError

    @property
    def table(self) -> List[List[int]]:
        raise NotImplementedError


class TopK:
    def __init__(self, k: int, sketch: CountMinSketch) -> None:
        raise NotImplementedError

    def add(self, item: Item, count: int = 1) -> bool:
        """返回 item 现在是否在候选集里。"""
        raise NotImplementedError

    def candidates(self) -> Set[Item]:
        raise NotImplementedError

    def top(self, n: Optional[int] = None) -> List[Tuple[Item, int]]:
        raise NotImplementedError


class TrendingTracker:
    def __init__(
        self,
        k: int,
        width: int,
        depth: int,
        *,
        window: float = 300.0,
        bucket: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        raise NotImplementedError

    def add(self, item: Item, count: int = 1) -> None:
        raise NotImplementedError

    def live_buckets(self) -> int:
        raise NotImplementedError

    def estimate(self, item: Item) -> int:
        raise NotImplementedError

    def trending(self, n: Optional[int] = None) -> List[Tuple[Item, int]]:
        raise NotImplementedError
