"""Day 05 · 带 WAL 的单机 KV 存储（崩溃恢复）。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
记录格式（大端）：crc32(4) | op(1) | key_len(4) | val_len(4) | key | value
fsync 请写成 os.fsync(...)，测试会替换它来数调用次数。
"""

from __future__ import annotations

import os  # noqa: F401
import struct  # noqa: F401  提示：struct.pack(">IBII", ...)
import zlib  # noqa: F401  提示：zlib.crc32
from pathlib import Path
from typing import List, Optional, Tuple, Union

OP_PUT = 1
OP_DELETE = 2
HEADER_SIZE = 13  # 4 + 1 + 4 + 4

WAL_FILE = "wal.log"
SNAPSHOT_FILE = "snapshot.dat"
SNAPSHOT_TMP_FILE = "snapshot.dat.tmp"

Record = Tuple[int, bytes, bytes]


def encode_record(op: int, key: bytes, value: bytes = b"") -> bytes:
    """按格式编码一条记录。op 不是 OP_PUT / OP_DELETE 抛 ValueError。"""
    raise NotImplementedError


def decode_records(data: bytes) -> Tuple[List[Record], int]:
    """依次解码，遇到不完整或损坏的记录就停下。

    返回 (records, valid_length)：records 是 [(op, key, value), ...]，
    valid_length 是最后一条完好记录的结尾位置（data[:valid_length] 全部完好）。
    """
    raise NotImplementedError


class KVStore:
    def __init__(
        self,
        directory: Union[str, Path],
        *,
        sync: bool = True,
        compact_threshold: Optional[int] = None,
    ) -> None:
        """打开（或新建）数据目录，并完成恢复：加载快照 → 重放 WAL → 截断尾部坏字节。"""
        raise NotImplementedError

    @property
    def recovered_records(self) -> int:
        """本次打开时从 wal.log 重放的记录条数（不含快照）。"""
        raise NotImplementedError

    @property
    def discarded_bytes(self) -> int:
        """本次打开时从 wal.log 末尾截掉的字节数。"""
        raise NotImplementedError

    def put(self, key: str, value: bytes) -> None:
        """先写 WAL（flush，sync=True 时 fsync），再改内存。"""
        raise NotImplementedError

    def get(self, key: str, default: Optional[bytes] = None) -> Optional[bytes]:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        """key 存在：写 DELETE 记录、删除并返回 True；不存在：什么都不写，返回 False。"""
        raise NotImplementedError

    def __contains__(self, key: str) -> bool:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def keys(self) -> List[str]:
        """排好序的所有 key。"""
        raise NotImplementedError

    def compact(self) -> None:
        """崩溃安全地写快照：写 tmp + fsync → os.replace → 截断 wal.log。"""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
