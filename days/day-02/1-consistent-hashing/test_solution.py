import importlib.util
import time
from collections import Counter
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "day02_ring_solution", Path(__file__).with_name("solution.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ConsistentHashRing = _mod.ConsistentHashRing
default_hash = _mod.default_hash


class TableHash:
    """测试用哈希：查表返回固定位置，同时记录被哈希过的字符串。"""

    def __init__(self, table):
        self.table = dict(table)
        self.calls = []

    def __call__(self, s):
        self.calls.append(s)
        if s not in self.table:
            raise AssertionError(f"测试没有预料到会哈希这个字符串: {s!r}")
        return self.table[s]


# 环（vnodes=1）：A#0=100, B#0=200, C#0=300
SIMPLE = {
    "A#0": 100,
    "B#0": 200,
    "C#0": 300,
    "k0": 0,
    "k50": 50,
    "k100": 100,
    "k101": 101,
    "k150": 150,
    "k200": 200,
    "k250": 250,
    "k300": 300,
    "k350": 350,
}


def simple_ring():
    return ConsistentHashRing(["A", "B", "C"], vnodes=1, hash_fn=TableHash(SIMPLE))


KEYS = [f"key-{i}" for i in range(20_000)]


def assignment(ring, keys=KEYS):
    return {k: ring.get_node(k) for k in keys}


# ---------- 参数校验 ----------


def test_invalid_vnodes():
    with pytest.raises(ValueError):
        ConsistentHashRing(vnodes=0)
    with pytest.raises(ValueError):
        ConsistentHashRing(vnodes=-5)


def test_invalid_weight():
    ring = ConsistentHashRing()
    with pytest.raises(ValueError):
        ring.add_node("a", weight=0)
    with pytest.raises(ValueError):
        ring.add_node("a", weight=-1)
    assert "a" not in ring


def test_duplicate_node_rejected():
    ring = ConsistentHashRing(["a"])
    with pytest.raises(ValueError):
        ring.add_node("a")
    assert len(ring) == 1


def test_remove_missing_node():
    ring = ConsistentHashRing(["a"])
    with pytest.raises(KeyError):
        ring.remove_node("b")


def test_empty_ring_lookup():
    ring = ConsistentHashRing()
    with pytest.raises(LookupError):
        ring.get_node("x")
    with pytest.raises(LookupError):
        ring.get_nodes("x", 1)


def test_get_nodes_invalid_n():
    ring = ConsistentHashRing(["a", "b"])
    with pytest.raises(ValueError):
        ring.get_nodes("x", 0)


def test_ring_becomes_empty_again():
    ring = ConsistentHashRing(["a"])
    ring.remove_node("a")
    assert len(ring) == 0
    with pytest.raises(LookupError):
        ring.get_node("x")


# ---------- 节点集合 ----------


def test_len_contains_and_nodes():
    ring = ConsistentHashRing(["a", "b"])
    ring.add_node("c", weight=2)
    assert len(ring) == 3
    assert "c" in ring
    assert "z" not in ring
    assert ring.nodes == {"a", "b", "c"}
    ring.remove_node("b")
    assert ring.nodes == {"a", "c"}


def test_nodes_returns_copy():
    ring = ConsistentHashRing(["a", "b"])
    s = ring.nodes
    s.add("hacker")
    s.discard("a")
    assert ring.nodes == {"a", "b"}


# ---------- 用固定哈希精确检查顺时针语义 ----------


def test_clockwise_lookup():
    ring = simple_ring()
    assert ring.get_node("k50") == "A"
    assert ring.get_node("k101") == "B"
    assert ring.get_node("k150") == "B"
    assert ring.get_node("k250") == "C"


def test_lookup_exact_position_belongs_to_that_node():
    ring = simple_ring()
    assert ring.get_node("k100") == "A"
    assert ring.get_node("k200") == "B"
    assert ring.get_node("k300") == "C"


def test_lookup_wraps_around():
    ring = simple_ring()
    assert ring.get_node("k350") == "A"
    assert ring.get_node("k0") == "A"


def test_vnode_labels_follow_format():
    h = TableHash({"A#0": 1, "A#1": 2, "A#2": 3})
    ConsistentHashRing(["A"], vnodes=3, hash_fn=h)
    assert sorted(c for c in h.calls) == ["A#0", "A#1", "A#2"]


def test_weight_controls_vnode_count():
    table = {f"W#{i}": 10 + i for i in range(10)}
    table.update({f"L#{i}": 100 + i for i in range(10)})
    h = TableHash(table)
    ring = ConsistentHashRing(vnodes=4, hash_fn=h)
    ring.add_node("W", weight=1.5)  # round(6) = 6
    ring.add_node("L", weight=0.1)  # round(0.4) = 0 -> 至少 1 个
    w_labels = sorted(c for c in h.calls if c.startswith("W#"))
    l_labels = sorted(c for c in h.calls if c.startswith("L#"))
    assert w_labels == [f"W#{i}" for i in range(6)]
    assert l_labels == ["L#0"]


def test_remove_moves_keys_to_next_node():
    ring = simple_ring()
    ring.remove_node("B")
    assert ring.get_node("k150") == "C"
    assert ring.get_node("k200") == "C"
    assert ring.get_node("k50") == "A"
    ring.remove_node("A")
    assert ring.get_node("k50") == "C"
    assert ring.get_node("k350") == "C"


def test_add_takes_over_only_its_arc():
    table = dict(SIMPLE)
    table["D#0"] = 250
    ring = ConsistentHashRing(["A", "B", "C"], vnodes=1, hash_fn=TableHash(table))
    ring.add_node("D")
    assert ring.get_node("k250") == "D"  # (200, 250] 归 D
    assert ring.get_node("k300") == "C"  # (250, 300] 还是 C
    assert ring.get_node("k150") == "B"


def test_removed_node_vnodes_all_gone():
    # A 有 3 个虚拟节点，删掉 A 后，原来落在 A 任何一个虚拟节点上的 key 都不能再返回 A
    table = {"A#0": 10, "A#1": 20, "A#2": 30, "B#0": 100, "B#1": 200, "B#2": 300}
    table.update({"x5": 5, "x15": 15, "x25": 25, "x350": 350})
    ring = ConsistentHashRing(["A", "B"], vnodes=3, hash_fn=TableHash(table))
    assert ring.get_node("x15") == "A"
    ring.remove_node("A")
    for k in ["x5", "x15", "x25", "x350"]:
        assert ring.get_node(k) == "B"


# ---------- 副本 ----------

# vnodes=2：C#1=50, A#0=100, A#1=150, B#0=200, B#1=250, C#0=300
REPLICA = {
    "A#0": 100,
    "A#1": 150,
    "B#0": 200,
    "B#1": 250,
    "C#0": 300,
    "C#1": 50,
    "r90": 90,
    "r120": 120,
    "r260": 260,
    "r400": 400,
}


def replica_ring():
    return ConsistentHashRing(["A", "B", "C"], vnodes=2, hash_fn=TableHash(REPLICA))


def test_get_nodes_skips_same_physical_node():
    ring = replica_ring()
    # 120 -> A#1(150) -> B#0 -> B#1(跳过) -> C#0
    assert ring.get_nodes("r120", 3) == ["A", "B", "C"]
    assert ring.get_nodes("r120", 2) == ["A", "B"]
    assert ring.get_nodes("r120", 1) == ["A"]


def test_get_nodes_wraps_around():
    ring = replica_ring()
    # 260 -> C#0(300) -> 绕回 C#1(50, 跳过) -> A#0 -> ... -> B
    assert ring.get_nodes("r260", 3) == ["C", "A", "B"]
    # 400 -> 绕回 C#1(50)
    assert ring.get_nodes("r400", 2) == ["C", "A"]


def test_get_nodes_more_than_available():
    ring = replica_ring()
    assert ring.get_nodes("r90", 10) == ["A", "B", "C"]


def test_get_nodes_first_equals_get_node():
    ring = ConsistentHashRing([f"n{i}" for i in range(7)], vnodes=50)
    for k in KEYS[:2000]:
        replicas = ring.get_nodes(k, 3)
        assert replicas[0] == ring.get_node(k)
        assert len(replicas) == 3
        assert len(set(replicas)) == 3


# ---------- 用默认哈希验证“一致性” ----------


def test_default_hash_is_used_by_default():
    ring = ConsistentHashRing(["a", "b", "c"], vnodes=10)
    explicit = ConsistentHashRing(["a", "b", "c"], vnodes=10, hash_fn=default_hash)
    assert assignment(ring, KEYS[:3000]) == assignment(explicit, KEYS[:3000])


def test_independent_of_insertion_order():
    names = [f"node-{i}" for i in range(8)]
    r1 = ConsistentHashRing(names, vnodes=50)
    r2 = ConsistentHashRing(vnodes=50)
    for n in reversed(names):
        r2.add_node(n)
    assert assignment(r1) == assignment(r2)


def test_add_then_remove_restores_assignment():
    ring = ConsistentHashRing([f"node-{i}" for i in range(5)], vnodes=80)
    before = assignment(ring)
    ring.add_node("temp", weight=3)
    ring.remove_node("temp")
    assert assignment(ring) == before


def test_adding_node_only_moves_keys_to_new_node():
    ring = ConsistentHashRing([f"node-{i}" for i in range(5)], vnodes=100)
    before = assignment(ring)
    ring.add_node("node-new")
    after = assignment(ring)
    moved = [k for k in KEYS if before[k] != after[k]]
    assert moved, "加了新节点却没有任何 key 迁移，不对"
    assert all(after[k] == "node-new" for k in moved)
    # 5 -> 6 个节点，理论上迁移约 1/6，不应该接近全部
    assert len(moved) / len(KEYS) < 0.3


def test_removing_node_only_moves_its_keys():
    ring = ConsistentHashRing([f"node-{i}" for i in range(6)], vnodes=100)
    before = assignment(ring)
    ring.remove_node("node-3")
    after = assignment(ring)
    for k in KEYS:
        if before[k] == "node-3":
            assert after[k] != "node-3"
        else:
            assert after[k] == before[k]


def test_modulo_comparison():
    """对照组：hash % N 加一台机器会搬走大部分 key，一致性哈希只搬一小部分。"""
    ring = ConsistentHashRing([f"node-{i}" for i in range(9)], vnodes=100)
    before = assignment(ring)
    ring.add_node("node-9")
    after = assignment(ring)
    ring_moved = sum(before[k] != after[k] for k in KEYS) / len(KEYS)

    mod_moved = sum(
        default_hash(k) % 9 != default_hash(k) % 10 for k in KEYS
    ) / len(KEYS)
    assert mod_moved > 0.8
    assert ring_moved < 0.2


# ---------- 负载均衡与权重 ----------


def test_load_balance_with_vnodes():
    ring = ConsistentHashRing([f"server-{i}" for i in range(10)], vnodes=200)
    keys = [f"obj:{i}" for i in range(100_000)]
    load = Counter(ring.get_node(k) for k in keys)
    assert set(load) == ring.nodes
    avg = len(keys) / 10
    assert max(load.values()) < avg * 1.3, load


def test_weight_roughly_proportional():
    ring = ConsistentHashRing([f"small-{i}" for i in range(6)], vnodes=200)
    ring.add_node("big", weight=2)
    keys = [f"obj:{i}" for i in range(100_000)]
    load = Counter(ring.get_node(k) for k in keys)
    small_avg = sum(load[f"small-{i}"] for i in range(6)) / 6
    ratio = load["big"] / small_avg
    assert 1.6 < ratio < 2.4, ratio


# ---------- 复杂度 ----------


def test_lookup_is_logarithmic():
    ring = ConsistentHashRing([f"n{i}" for i in range(100)], vnodes=200)  # 2 万个虚拟节点
    keys = [f"q{i}" for i in range(100_000)]
    start = time.perf_counter()
    for k in keys:
        ring.get_node(k)
    elapsed = time.perf_counter() - start
    # O(log V) 大约 0.3 秒；每次线性扫描会是几分钟
    assert elapsed < 5, f"10 万次查找用了 {elapsed:.1f}s，看起来不是 O(log V)"
