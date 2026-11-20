import hashlib
import importlib.util
import random
import sys
import time
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day16_merkle_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
leaf_hash = _mod.leaf_hash
node_hash = _mod.node_hash
MerkleTree = _mod.MerkleTree
diff = _mod.diff
bucket_of = _mod.bucket_of
bucket_block = _mod.bucket_block
build_store_tree = _mod.build_store_tree
anti_entropy = _mod.anti_entropy


def H(b):
    return hashlib.sha256(b).digest()


def blocks(n, tag=b"blk"):
    return [tag + str(i).encode() for i in range(n)]


# =====================================================================
# 建树
# =====================================================================


def test_build_hash_rules():
    assert leaf_hash(b"x") == H(b"\x00x")
    assert node_hash(b"L" * 32, b"R" * 32) == H(b"\x01" + b"L" * 32 + b"R" * 32)


def test_build_single_block():
    t = MerkleTree([b"only"])
    assert t.root == leaf_hash(b"only")
    assert len(t) == 1 and t.height == 0


def test_build_four_blocks():
    bs = [b"a", b"b", b"c", b"d"]
    t = MerkleTree(bs)
    l = [leaf_hash(x) for x in bs]
    assert t.root == node_hash(node_hash(l[0], l[1]), node_hash(l[2], l[3]))
    assert t.height == 2
    assert t.node(0, 2) == l[2]
    assert t.node(1, 1) == node_hash(l[2], l[3])


def test_build_odd_count_promotes_last():
    bs = [b"a", b"b", b"c"]
    t = MerkleTree(bs)
    l = [leaf_hash(x) for x in bs]
    assert t.node(1, 1) == l[2], "奇数个时最后一个原样提升"
    assert t.root == node_hash(node_hash(l[0], l[1]), l[2])
    l5 = [leaf_hash(x) for x in [b"1", b"2", b"3", b"4", b"5"]]
    t5 = MerkleTree([b"1", b"2", b"3", b"4", b"5"])
    assert t5.root == node_hash(node_hash(node_hash(l5[0], l5[1]), node_hash(l5[2], l5[3])), l5[4])
    assert t5.height == 3


def test_build_invalid():
    with pytest.raises(ValueError):
        MerkleTree([])
    with pytest.raises(TypeError):
        MerkleTree([b"ok", "not bytes"])


def test_build_root_changes_with_any_block_or_order():
    base = MerkleTree(blocks(10)).root
    for i in range(10):
        bs = blocks(10)
        bs[i] = b"evil"
        assert MerkleTree(bs).root != base
    bs = blocks(10)
    bs[0], bs[1] = bs[1], bs[0]
    assert MerkleTree(bs).root != base


# =====================================================================
# 证明
# =====================================================================


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 13, 64])
def test_proof_verifies_every_leaf(n):
    bs = blocks(n)
    t = MerkleTree(bs)
    for i in range(n):
        p = t.proof(i)
        assert MerkleTree.verify(t.root, bs[i], p)
        assert not MerkleTree.verify(t.root, bs[i] + b"!", p)


def test_proof_shape():
    t = MerkleTree([b"a", b"b", b"c", b"d"])
    l = [leaf_hash(x) for x in [b"a", b"b", b"c", b"d"]]
    assert t.proof(2) == [(l[3], False), (node_hash(l[0], l[1]), True)]
    t3 = MerkleTree([b"a", b"b", b"c"])
    assert t3.proof(2) == [(node_hash(l[0], l[1]), True)], "被提升的那一层没有兄弟，跳过"


def test_proof_size_is_logarithmic():
    t = MerkleTree(blocks(1024))
    assert len(t.proof(517)) == 10


def test_proof_wrong_position_fails():
    bs = blocks(8)
    t = MerkleTree(bs)
    assert not MerkleTree.verify(t.root, bs[3], t.proof(4))


def test_proof_index_error():
    t = MerkleTree(blocks(4))
    with pytest.raises(IndexError):
        t.proof(4)
    with pytest.raises(IndexError):
        t.proof(-1)


# =====================================================================
# 增量更新
# =====================================================================


@pytest.mark.parametrize("n", [1, 2, 7, 16, 33])
def test_update_matches_rebuild(n):
    rnd = random.Random(n)
    bs = blocks(n)
    t = MerkleTree(bs)
    for _ in range(20):
        i = rnd.randrange(n)
        bs[i] = rnd.randbytes(8)
        t.update(i, bs[i])
        fresh = MerkleTree(bs)
        assert t.root == fresh.root
        assert all(t.node(0, j) == fresh.node(0, j) for j in range(n))


def test_update_is_logarithmic():
    t = MerkleTree(blocks(100_000))
    start = time.perf_counter()
    for i in range(2000):
        t.update(i * 37 % 100_000, b"new" + str(i).encode())
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"2000 次 update 用了 {elapsed:.2f}s，是不是每次都整棵重建了？"


def test_update_index_error():
    with pytest.raises(IndexError):
        MerkleTree(blocks(3)).update(3, b"x")


# =====================================================================
# diff
# =====================================================================


def test_diff_identical():
    assert diff(MerkleTree(blocks(100)), MerkleTree(blocks(100))) == ([], 1)


@pytest.mark.parametrize("h", [1, 3, 10])
def test_diff_single_change_count(h):
    n = 1 << h
    a = blocks(n)
    b = list(a)
    b[n // 3] = b"changed"
    res = diff(MerkleTree(a), MerkleTree(b))
    assert res.indices == [n // 3]
    assert res.nodes_compared == 1 + 2 * h


def test_diff_finds_all_changes():
    rnd = random.Random(16)
    a = blocks(1000)
    b = list(a)
    changed = sorted(rnd.sample(range(1000), 15))
    for i in changed:
        b[i] = b"x" + b[i]
    res = diff(MerkleTree(a), MerkleTree(b))
    assert res.indices == changed
    assert res.nodes_compared < 15 * 2 * 11, "只往不同的子树走"


def test_diff_odd_sizes():
    for n in (3, 5, 9, 31):
        a = blocks(n)
        b = list(a)
        b[-1] = b"last-changed"
        b[0] = b"first-changed"
        assert diff(MerkleTree(a), MerkleTree(b)).indices == [0, n - 1]


def test_diff_size_mismatch():
    with pytest.raises(ValueError):
        diff(MerkleTree(blocks(4)), MerkleTree(blocks(5)))


# =====================================================================
# 反熵
# =====================================================================


def test_entropy_bucket_of():
    for key in ["a", "user:42", "购物车"]:
        x = int.from_bytes(H(key.encode())[:4], "big")
        assert bucket_of(key, 8) == x >> 24
        assert bucket_of(key, 1) == x >> 31
        assert 0 <= bucket_of(key, 20) < (1 << 20)


def test_entropy_bucket_block_encoding():
    assert bucket_block([]) == H(b"")
    items = [("b", "2"), ("a", "1")]
    expected = H(b"\x00\x00\x00\x01a\x00\x00\x00\x011" + b"\x00\x00\x00\x01b\x00\x00\x00\x012")
    assert bucket_block(items) == expected
    assert bucket_block([("ab", "c")]) != bucket_block([("a", "bc")]), "写长度才能区分拼接的边界"
    assert bucket_block([("键", "值")]) == H(b"\x00\x00\x00\x03" + "键".encode() + b"\x00\x00\x00\x03" + "值".encode())


def test_entropy_build_store_tree():
    store = {f"k{i}": str(i) for i in range(500)}
    t = build_store_tree(store, 6)
    assert len(t) == 64
    bucket = [(k, v) for k, v in store.items() if bucket_of(k, 6) == 5]
    assert t.node(0, 5) == leaf_hash(bucket_block(bucket))
    with pytest.raises(ValueError):
        build_store_tree(store, 0)
    with pytest.raises(ValueError):
        build_store_tree(store, 21)


def test_entropy_identical_stores():
    s = {f"k{i}": "v" for i in range(1000)}
    assert anti_entropy(s, dict(s)) == []


def test_entropy_finds_differences():
    a = {f"k{i}": str(i) for i in range(5000)}
    b = dict(a)
    b["k17"] = "changed"
    del b["k4000"]
    b["new-key"] = "x"
    assert anti_entropy(a, b, depth=10) == ["k17", "k4000", "new-key"]


def test_entropy_random_against_brute_force():
    rnd = random.Random(7)
    a = {f"user:{i}": str(rnd.randrange(100)) for i in range(3000)}
    b = dict(a)
    for _ in range(40):
        k = f"user:{rnd.randrange(3500)}"
        op = rnd.random()
        if op < 0.4:
            b[k] = "updated"
        elif op < 0.7:
            b.pop(k, None)
        else:
            a.pop(k, None)
    expected = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    assert anti_entropy(a, b, depth=7) == expected
