"""Day 16 · Merkle 树（校验、证明、快速找差异）。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
叶子：sha256(b"\\x00" + data)；内部节点：sha256(b"\\x01" + left + right)；都用 .digest()。
奇数个节点时，最后一个原样提升到上一层。
"""

from __future__ import annotations

import hashlib  # noqa: F401
from typing import Dict, List, NamedTuple, Sequence, Tuple

Proof = List[Tuple[bytes, bool]]  # [(兄弟哈希, 兄弟是否在左边), ...]，从叶子往上


def leaf_hash(data: bytes) -> bytes:
    raise NotImplementedError


def node_hash(left: bytes, right: bytes) -> bytes:
    raise NotImplementedError


class DiffResult(NamedTuple):
    indices: List[int]
    nodes_compared: int


class MerkleTree:
    def __init__(self, blocks: Sequence[bytes]) -> None:
        raise NotImplementedError

    @property
    def root(self) -> bytes:
        raise NotImplementedError

    def __len__(self) -> int:
        """叶子个数。"""
        raise NotImplementedError

    @property
    def height(self) -> int:
        """层数减 1，只有一个叶子时为 0。"""
        raise NotImplementedError

    def node(self, level: int, index: int) -> bytes:
        """第 level 层（叶子为第 0 层）第 index 个节点的哈希。"""
        raise NotImplementedError

    def proof(self, index: int) -> Proof:
        raise NotImplementedError

    @staticmethod
    def verify(root: bytes, block: bytes, proof: Proof) -> bool:
        raise NotImplementedError

    def update(self, index: int, block: bytes) -> None:
        """只重算从这个叶子到根的路径。"""
        raise NotImplementedError


def diff(a: MerkleTree, b: MerkleTree) -> DiffResult:
    """从根开始递归，只往哈希不同的子树走。"""
    raise NotImplementedError


def bucket_of(key: str, depth: int) -> int:
    """sha256(key) 前 4 字节（大端整数）的最高 depth 位。"""
    raise NotImplementedError


def bucket_block(items: Sequence[Tuple[str, str]]) -> bytes:
    """按 key 排序，逐项写入 长度+key+长度+value，再取 sha256 digest。"""
    raise NotImplementedError


def build_store_tree(store: Dict[str, str], depth: int) -> MerkleTree:
    raise NotImplementedError


def anti_entropy(store_a: Dict[str, str], store_b: Dict[str, str], depth: int = 8) -> List[str]:
    """只在 diff 出来的桶里逐个比较 key，返回不一致的 key（排好序）。"""
    raise NotImplementedError
