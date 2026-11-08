"""Day 04 · 布隆过滤器（标准版 + 计数版）。

题目见同目录 README.md。只填实现，不要改公开方法的签名。
哈希一律用 hashlib，不要用 Python 内置的 hash()（它每个进程的种子不一样）。
"""

from __future__ import annotations

import hashlib  # noqa: F401  提示：双重哈希的两个基础哈希从这里来
import math  # noqa: F401
from typing import Union

Item = Union[str, bytes]


def optimal_num_bits(capacity: int, error_rate: float) -> int:
    """m = ceil(-n * ln(p) / (ln 2)^2)"""
    raise NotImplementedError


def optimal_num_hashes(num_bits: int, capacity: int) -> int:
    """k = round(m / n * ln 2)，至少为 1。"""
    raise NotImplementedError


class BloomFilter:
    def __init__(self, capacity: int, error_rate: float = 0.01) -> None:
        """capacity：预计插入的元素个数 n；error_rate：插满 n 个时期望的误判率 p。"""
        raise NotImplementedError

    @property
    def num_bits(self) -> int:
        raise NotImplementedError

    @property
    def num_hashes(self) -> int:
        raise NotImplementedError

    @property
    def size_in_bytes(self) -> int:
        """位数组占用的字节数，等于 ceil(num_bits / 8)。"""
        raise NotImplementedError

    def add(self, item: Item) -> bool:
        """插入 item。插入前「肯定不在」（至少有一位从 0 变成 1）返回 True，否则返回 False。"""
        raise NotImplementedError

    def __contains__(self, item: Item) -> bool:
        """False 表示肯定不在；True 表示可能在。"""
        raise NotImplementedError

    def approx_count(self) -> float:
        """根据置 1 的位数 X 估算插入过多少个不同元素：-(m / k) * ln(1 - X / m)。"""
        raise NotImplementedError

    def false_positive_rate(self) -> float:
        """按当前置 1 的比例估算误判率：(X / m) ** k。"""
        raise NotImplementedError

    def union(self, other: "BloomFilter") -> "BloomFilter":
        """返回一个新过滤器，包含两者的全部元素。参数不同抛 ValueError。不修改 self 和 other。"""
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        """序列化：包含 capacity、error_rate（或 m、k）和位数组，能被 from_bytes 还原。"""
        raise NotImplementedError

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        raise NotImplementedError


class CountingBloomFilter:
    """每个位置换成一个 8 位计数器（0..255），支持删除。"""

    def __init__(self, capacity: int, error_rate: float = 0.01) -> None:
        raise NotImplementedError

    @property
    def num_bits(self) -> int:
        """计数器个数 m，和同参数的 BloomFilter 相同。"""
        raise NotImplementedError

    @property
    def num_hashes(self) -> int:
        raise NotImplementedError

    def add(self, item: Item) -> None:
        raise NotImplementedError

    def remove(self, item: Item) -> bool:
        """item 肯定不在时什么都不改，返回 False；否则每个计数器减 1（255 的不减），返回 True。"""
        raise NotImplementedError

    def __contains__(self, item: Item) -> bool:
        raise NotImplementedError

    def count(self, item: Item) -> int:
        """item 被插入次数的上界估计：k 个计数器里的最小值。"""
        raise NotImplementedError
