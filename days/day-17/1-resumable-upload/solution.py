"""Day 17 · 分块上传 + 断点续传 + 秒传。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
哈希一律用 sha256_hex（已经写好）。时间一律通过注入的 clock() 取。
"""

from __future__ import annotations

import hashlib
import math  # noqa: F401
import time
import uuid  # noqa: F401
from typing import Callable, List, NamedTuple, Optional


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ChecksumError(ValueError):
    """数据的哈希和声明的不一致。"""


class ChunkConflictError(ValueError):
    """同一块已经收到过，但这次的内容不一样。"""


class IncompleteUploadError(RuntimeError):
    def __init__(self, missing: List[int]) -> None:
        super().__init__(f"missing chunks: {missing}")
        self.missing = missing


class UploadInterrupted(RuntimeError):
    """某一块重试次数用完。upload_id 留给调用方以后续传。"""

    def __init__(self, upload_id: str) -> None:
        super().__init__(f"upload {upload_id} interrupted")
        self.upload_id = upload_id


class UploadResult(NamedTuple):
    file_id: str
    upload_id: Optional[str]
    chunks_sent: int
    deduplicated: bool


class UploadServer:
    def __init__(
        self,
        chunk_size: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        session_ttl: float = 86400.0,
        max_file_size: int = 50 * 2**30,
    ) -> None:
        """公开属性：chunk_size。"""
        raise NotImplementedError

    def has_file(self, sha256: str) -> bool:
        raise NotImplementedError

    def get_file(self, file_id: str) -> bytes:
        raise NotImplementedError

    def create_session(self, name: str, total_size: int, sha256: str) -> str:
        raise NotImplementedError

    def num_chunks(self, upload_id: str) -> int:
        raise NotImplementedError

    def upload_chunk(self, upload_id: str, index: int, data: bytes, chunk_sha256: str) -> None:
        raise NotImplementedError

    def missing_chunks(self, upload_id: str) -> List[int]:
        raise NotImplementedError

    def complete(self, upload_id: str) -> str:
        raise NotImplementedError

    def active_sessions(self) -> int:
        raise NotImplementedError


def upload_file(
    server: UploadServer,
    name: str,
    data: bytes,
    *,
    max_attempts: int = 3,
    upload_id: Optional[str] = None,
) -> UploadResult:
    """秒传 → 续传或新建会话 → 逐块上传（每块最多 max_attempts 次）→ complete。"""
    raise NotImplementedError
