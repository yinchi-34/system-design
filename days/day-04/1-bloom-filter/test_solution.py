import importlib.util
import math
import os
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day04_bloom_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
optimal_num_bits = _mod.optimal_num_bits
optimal_num_hashes = _mod.optimal_num_hashes
BloomFilter = _mod.BloomFilter
CountingBloomFilter = _mod.CountingBloomFilter


def urls(prefix, n):
    return [f"https://{prefix}.example.com/page/{i}" for i in range(n)]


# =====================================================================
# 参数计算
# =====================================================================


@pytest.mark.parametrize(
    "n, p, m, k",
    [
        (1000, 0.01, 9586, 7),
        (1_000_000, 0.01, 9_585_059, 7),
        (1000, 0.001, 14378, 10),
        (100, 0.1, 480, 3),
        (1, 0.5, 2, 1),
    ],
)
def test_bloom_optimal_params(n, p, m, k):
    assert optimal_num_bits(n, p) == m
    assert optimal_num_hashes(m, n) == k


def test_bloom_num_hashes_at_least_one():
    assert optimal_num_hashes(1, 100) == 1


@pytest.mark.parametrize("cls", [BloomFilter, CountingBloomFilter])
@pytest.mark.parametrize("n, p", [(0, 0.01), (-5, 0.01), (100, 0), (100, 1), (100, -0.1), (100, 1.5)])
def test_bloom_invalid_args(cls, n, p):
    with pytest.raises(ValueError):
        cls(n, p)


def test_bloom_properties():
    bf = BloomFilter(1000, 0.01)
    assert bf.num_bits == 9586
    assert bf.num_hashes == 7
    assert bf.size_in_bytes == math.ceil(9586 / 8)


# =====================================================================
# 标准布隆过滤器
# =====================================================================

# ---------- 基本行为 ----------


def test_bloom_empty_contains_nothing():
    bf = BloomFilter(100)
    assert "a" not in bf
    assert "" not in bf
    assert bf.approx_count() == 0
    assert bf.false_positive_rate() == 0


def test_bloom_add_then_contains():
    bf = BloomFilter(100)
    bf.add("hello")
    assert "hello" in bf


def test_bloom_add_returns_whether_new():
    bf = BloomFilter(1000)
    assert bf.add("x") is True
    assert bf.add("x") is False
    assert bf.add("y") is True


def test_bloom_str_and_bytes_are_same_item():
    bf = BloomFilter(100)
    bf.add("网页")
    assert "网页".encode("utf-8") in bf
    bf.add(b"abc")
    assert "abc" in bf


@pytest.mark.parametrize("bad", [123, None, 1.5, ["a"]])
def test_bloom_rejects_other_types(bad):
    bf = BloomFilter(100)
    with pytest.raises(TypeError):
        bf.add(bad)
    with pytest.raises(TypeError):
        bad in bf  # noqa: B015


def test_bloom_no_false_negatives():
    bf = BloomFilter(5000, 0.01)
    items = urls("a", 5000)
    for u in items:
        bf.add(u)
    assert all(u in bf for u in items)


def test_bloom_no_false_negatives_even_when_overfilled():
    bf = BloomFilter(100, 0.01)
    items = urls("over", 2000)  # 塞进 20 倍容量
    for u in items:
        bf.add(u)
    assert all(u in bf for u in items)


# ---------- 误判率 ----------


def test_bloom_false_positive_rate_matches_target():
    n, p = 10_000, 0.01
    bf = BloomFilter(n, p)
    for u in urls("in", n):
        bf.add(u)
    probes = urls("out", 100_000)
    fp = sum(u in bf for u in probes) / len(probes)
    assert fp < p * 1.5, f"实测误判率 {fp:.4f}，目标 {p}，哈希分布可能不均匀"


def test_bloom_lower_error_rate_means_fewer_false_positives():
    n = 5000
    loose, tight = BloomFilter(n, 0.05), BloomFilter(n, 0.001)
    for u in urls("in", n):
        loose.add(u)
        tight.add(u)
    probes = urls("out", 50_000)
    fp_loose = sum(u in loose for u in probes)
    fp_tight = sum(u in tight for u in probes)
    assert fp_tight < fp_loose / 10


def test_bloom_estimated_fpr_near_target_when_full():
    bf = BloomFilter(10_000, 0.01)
    for u in urls("in", 10_000):
        bf.add(u)
    assert 0.005 < bf.false_positive_rate() < 0.02


def test_bloom_estimated_fpr_grows_when_overfilled():
    bf = BloomFilter(1000, 0.01)
    for u in urls("in", 1000):
        bf.add(u)
    full = bf.false_positive_rate()
    for u in urls("more", 2000):
        bf.add(u)
    assert bf.false_positive_rate() > full * 10


def test_bloom_approx_count():
    bf = BloomFilter(10_000, 0.01)
    for u in urls("in", 6000):
        bf.add(u)
    for u in urls("in", 6000):  # 重复插入不应该影响估算
        bf.add(u)
    assert bf.approx_count() == pytest.approx(6000, rel=0.03)


# ---------- 哈希要稳定、内存要省 ----------


def test_bloom_two_filters_same_params_are_identical():
    a, b = BloomFilter(1000), BloomFilter(1000)
    for u in urls("x", 300):
        a.add(u)
        b.add(u)
    assert a.to_bytes() == b.to_bytes()


def _digest_in_subprocess(hashseed):
    code = (
        "import hashlib, importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('s', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "bf = m.BloomFilter(1000)\n"
        "for i in range(300): bf.add(f'https://x.example.com/page/{i}')\n"
        "print(hashlib.sha256(bf.to_bytes()).hexdigest())\n"
    )
    env = dict(os.environ, PYTHONHASHSEED=str(hashseed))
    out = subprocess.run(
        [sys.executable, "-c", code, str(_SOLUTION)],
        env=env, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_bloom_hash_stable_across_processes():
    # 爬虫重启后要从磁盘加载过滤器继续用，所以不同进程算出来的位置必须一样。
    assert _digest_in_subprocess(1) == _digest_in_subprocess(2)


def test_bloom_memory_is_a_real_bit_array():
    tracemalloc.start()
    try:
        bf = BloomFilter(1_000_000, 0.01)  # 约 960 万位 ≈ 1.2 MB
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert bf.size_in_bytes == math.ceil(bf.num_bits / 8)
    assert peak < 3 * 1024 * 1024, f"峰值内存 {peak / 1e6:.1f} MB，应该用位数组而不是 list/set"


# ---------- 合并与序列化 ----------


def test_bloom_union_contains_both():
    a, b = BloomFilter(1000), BloomFilter(1000)
    for u in urls("a", 200):
        a.add(u)
    for u in urls("b", 200):
        b.add(u)
    c = a.union(b)
    assert all(u in c for u in urls("a", 200))
    assert all(u in c for u in urls("b", 200))
    assert c.approx_count() == pytest.approx(400, rel=0.05)


def test_bloom_union_does_not_modify_inputs():
    a, b = BloomFilter(1000), BloomFilter(1000)
    a.add("only-a")
    b.add("only-b")
    before_a, before_b = a.to_bytes(), b.to_bytes()
    a.union(b)
    assert a.to_bytes() == before_a
    assert b.to_bytes() == before_b


def test_bloom_union_requires_same_params():
    with pytest.raises(ValueError):
        BloomFilter(1000, 0.01).union(BloomFilter(2000, 0.01))
    with pytest.raises(ValueError):
        BloomFilter(1000, 0.01).union(BloomFilter(1000, 0.001))


def test_bloom_serialization_roundtrip():
    bf = BloomFilter(2000, 0.005)
    items = urls("s", 1500)
    for u in items:
        bf.add(u)
    data = bf.to_bytes()
    assert isinstance(data, bytes)
    assert len(data) < bf.size_in_bytes + 64, "序列化只应在位数组外加一个很小的头"
    restored = BloomFilter.from_bytes(data)
    assert restored.num_bits == bf.num_bits
    assert restored.num_hashes == bf.num_hashes
    assert all(u in restored for u in items)
    assert restored.to_bytes() == data
    restored.add("new-after-restore")
    assert "new-after-restore" in restored
    assert "new-after-restore" not in bf  # 还原出来的是独立副本


# =====================================================================
# 计数布隆过滤器
# =====================================================================


def test_counting_same_params_as_bloom():
    c = CountingBloomFilter(1000, 0.01)
    assert c.num_bits == 9586
    assert c.num_hashes == 7


def test_counting_add_contains_remove():
    c = CountingBloomFilter(1000)
    c.add("a")
    assert "a" in c
    assert c.remove("a") is True
    assert "a" not in c


def test_counting_count_tracks_multiplicity():
    c = CountingBloomFilter(1000)
    for _ in range(3):
        c.add("x")
    assert c.count("x") == 3
    c.remove("x")
    assert c.count("x") == 2
    assert "x" in c
    c.remove("x")
    c.remove("x")
    assert c.count("x") == 0
    assert "x" not in c


def test_counting_count_is_upper_bound():
    c = CountingBloomFilter(500)
    items = urls("c", 500)
    for i, u in enumerate(items):
        for _ in range(i % 4 + 1):
            c.add(u)
    for i, u in enumerate(items):
        assert c.count(u) >= i % 4 + 1


def test_counting_remove_absent_changes_nothing():
    c = CountingBloomFilter(1000)
    for u in urls("keep", 100):
        c.add(u)
    assert c.remove("never-added-and-not-a-false-positive-hopefully") is False
    assert all(u in c for u in urls("keep", 100))


def test_counting_remove_does_not_hurt_others():
    c = CountingBloomFilter(2000)
    keep, drop = urls("keep", 1000), urls("drop", 1000)
    for u in keep + drop:
        c.add(u)
    for u in drop:
        assert c.remove(u) is True
    assert all(u in c for u in keep), "删除别的元素导致了假阴性"
    still_there = sum(u in c for u in drop)
    assert still_there < 50, "删掉的元素大部分应该查不到了"


def test_counting_saturates_and_sticks():
    c = CountingBloomFilter(100)
    for _ in range(300):
        c.add("hot")
    assert c.count("hot") == 255
    for _ in range(300):
        c.remove("hot")
    # 计数器溢出后就不知道真实值了，只能永远保留，宁可误判也不能假阴性。
    assert "hot" in c
    assert c.count("hot") == 255


def test_counting_rejects_other_types():
    c = CountingBloomFilter(100)
    with pytest.raises(TypeError):
        c.add(42)
    with pytest.raises(TypeError):
        c.remove(42)
