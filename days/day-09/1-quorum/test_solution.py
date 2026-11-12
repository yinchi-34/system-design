import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day09_quorum_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
VectorClock = _mod.VectorClock
QuorumStore = _mod.QuorumStore
QuorumError = _mod.QuorumError

NODES = ["n1", "n2", "n3", "n4", "n5"]
VC = VectorClock


def clocks(sibs):
    return {c for _, c in sibs}


def values(sibs):
    return sorted(v for v, _ in sibs)


# =====================================================================
# 向量时钟
# =====================================================================


def test_clock_basics():
    c = VC({"a": 2, "b": 1})
    assert c.get("a") == 2 and c.get("zzz") == 0
    assert c.to_dict() == {"a": 2, "b": 1}
    assert VC({"a": 0}) == VC() == VC(None)
    assert VC({"a": 0, "b": 1}).to_dict() == {"b": 1}


@pytest.mark.parametrize("bad", [{"a": -1}, {"a": 1.5}, {"a": "1"}])
def test_clock_invalid(bad):
    with pytest.raises(ValueError):
        VC(bad)


def test_clock_immutable_increment_and_merge():
    c = VC({"a": 1})
    d = c.increment("a").increment("b")
    assert c.to_dict() == {"a": 1}
    assert d.to_dict() == {"a": 2, "b": 1}
    m = VC({"a": 3, "b": 1}).merge(VC({"b": 5, "c": 2}))
    assert m.to_dict() == {"a": 3, "b": 5, "c": 2}


@pytest.mark.parametrize(
    "x, y, expected",
    [
        ({}, {}, "equal"),
        ({"a": 1}, {"a": 1}, "equal"),
        ({"a": 1}, {"a": 2}, "before"),
        ({"a": 2}, {"a": 1}, "after"),
        ({}, {"a": 1}, "before"),
        ({"a": 1, "b": 1}, {"a": 1}, "after"),
        ({"a": 1}, {"b": 1}, "concurrent"),
        ({"a": 2, "b": 1}, {"a": 1, "b": 2}, "concurrent"),
    ],
)
def test_clock_compare(x, y, expected):
    assert VC(x).compare(VC(y)) == expected


def test_clock_descends():
    assert VC({"a": 2, "b": 1}).descends(VC({"a": 1}))
    assert VC({"a": 1}).descends(VC({"a": 1}))
    assert not VC({"a": 1}).descends(VC({"b": 1}))
    assert VC({"a": 1}).descends(VC())


def test_clock_hashable():
    s = {VC({"a": 1}), VC({"a": 1, "b": 0}), VC({"b": 1})}
    assert len(s) == 2


# =====================================================================
# 偏好列表
# =====================================================================


def _expected_pref(key, nodes, n):
    score = lambda x: int.from_bytes(hashlib.sha256(f"{key}|{x}".encode()).digest()[:8], "big")  # noqa: E731
    return sorted(nodes, key=lambda x: (-score(x), x))[:n]


@pytest.mark.parametrize("key", ["cart:1", "cart:2", "user:张三", ""])
def test_preference_list_rendezvous(key):
    st = QuorumStore(NODES, n=3)
    assert st.preference_list(key) == _expected_pref(key, NODES, 3)


def test_preference_list_minimal_movement():
    keys = [f"k{i}" for i in range(500)]
    before = QuorumStore(NODES, n=1, w=1, r=1)
    after = QuorumStore(NODES + ["n6"], n=1, w=1, r=1)
    moved = [k for k in keys if before.preference_list(k) != after.preference_list(k)]
    assert all(after.preference_list(k) == ["n6"] for k in moved), "加节点时只有归属新节点的 key 才移动"
    assert 40 < len(moved) < 140  # 约 1/6


@pytest.mark.parametrize(
    "kwargs",
    [{"n": 0}, {"n": 6}, {"w": 0}, {"w": 4}, {"r": 0}, {"r": 4}],
)
def test_quorum_invalid_params(kwargs):
    with pytest.raises(ValueError):
        QuorumStore(NODES, **kwargs)


def test_quorum_duplicate_nodes():
    with pytest.raises(ValueError):
        QuorumStore(["a", "a", "b"], n=2, w=1, r=1)


# =====================================================================
# 基本读写
# =====================================================================


def test_put_get_basic():
    st = QuorumStore(NODES)
    assert st.get("k") == ([], VC())
    c = st.put("k", "v1")
    p = st.preference_list("k")
    assert c == VC({p[0]: 1})
    vals, ctx = st.get("k")
    assert vals == ["v1"] and ctx == c


def test_put_writes_w_sync_rest_pending():
    st = QuorumStore(NODES, n=3, w=2, r=2)
    p = st.preference_list("k")
    st.put("k", "v")
    assert values(st.replica(p[0], "k")) == ["v"]
    assert values(st.replica(p[1], "k")) == ["v"]
    assert st.replica(p[2], "k") == []
    assert st.deliver_pending() == 1
    assert values(st.replica(p[2], "k")) == ["v"]
    assert st.deliver_pending() == 0
    others = [x for x in NODES if x not in p]
    assert all(st.replica(x, "k") == [] for x in others)


def test_put_with_context_supersedes():
    st = QuorumStore(NODES)
    st.put("k", "v1")
    _, ctx = st.get("k")
    c2 = st.put("k", "v2", ctx)
    assert c2.compare(ctx) == "after"
    st.deliver_pending()
    vals, _ = st.get("k")
    assert vals == ["v2"]
    p = st.preference_list("k")
    assert all(values(st.replica(x, "k")) == ["v2"] for x in p)


def test_put_coordinator_choice():
    st = QuorumStore(NODES)
    p = st.preference_list("k")
    c = st.put("k", "v", coordinator=p[2])
    assert c == VC({p[2]: 1})
    assert values(st.replica(p[2], "k")) == ["v"]
    assert values(st.replica(p[0], "k")) == ["v"]  # 协调者 + 偏好列表第一个，共 W=2 个
    assert st.replica(p[1], "k") == []
    with pytest.raises(ValueError):
        st.put("k", "v", coordinator=[x for x in NODES if x not in p][0])


def test_put_coordinator_must_be_up():
    st = QuorumStore(NODES)
    p = st.preference_list("k")
    st.set_down(p[0])
    with pytest.raises(ValueError):
        st.put("k", "v", coordinator=p[0])
    c = st.put("k", "v")
    assert c == VC({p[1]: 1})


def test_get_reads_first_r_up_nodes():
    st = QuorumStore(NODES, n=3, w=1, r=1)
    p = st.preference_list("k")
    st.set_down(p[0])
    st.put("k", "new")          # 只同步写到 p[1]
    st.set_up(p[0])
    vals, _ = st.get("k")        # R=1 只读 p[0]
    assert vals == [], "W + R <= N 时可以读到旧数据"


def test_get_overlap_when_w_plus_r_gt_n():
    st = QuorumStore(NODES, n=3, w=2, r=2)
    p = st.preference_list("k")
    st.set_down(p[0])
    st.put("k", "new")           # 写到 p[1], p[2]
    st.set_up(p[0])
    vals, _ = st.get("k")        # 读 p[0], p[1]：p[1] 有新值
    assert vals == ["new"]


def test_deliver_pending_drops_for_down_nodes():
    st = QuorumStore(NODES, n=3, w=1, r=1)
    p = st.preference_list("k")
    st.put("k", "v")
    st.set_down(p[2])
    assert st.deliver_pending() == 1
    st.set_up(p[2])
    assert st.replica(p[2], "k") == []
    assert st.deliver_pending() == 0


def test_replica_ignores_older_or_equal_version():
    st = QuorumStore(NODES, n=3, w=3, r=1)
    p = st.preference_list("k")
    c1 = st.put("k", "v1")
    _, ctx = st.get("k")
    st.put("k", "v2", ctx)
    # 一条迟到的旧写（比如网络里重传的包）不能覆盖新值
    st.put("k", "late-v1", None, coordinator=p[0])  # 时钟 {p0:1}，与 c1 相等
    assert c1 == VC({p[0]: 1})
    assert values(st.replica(p[0], "k")) == ["v2"]


# =====================================================================
# 兄弟版本（并发写）
# =====================================================================


def _concurrent_setup():
    st = QuorumStore(NODES, n=3, w=2, r=3)
    p = st.preference_list("cart")
    st.put("cart", "base")
    st.deliver_pending()
    _, ctx = st.get("cart")
    ca = st.put("cart", "milk", ctx, coordinator=p[0])
    cb = st.put("cart", "egg", ctx, coordinator=p[1])
    return st, p, ctx, ca, cb


def test_sibling_created_by_concurrent_writes():
    st, p, ctx, ca, cb = _concurrent_setup()
    assert ca.compare(cb) == "concurrent"
    st.deliver_pending()
    vals, merged = st.get("cart")
    assert sorted(vals) == ["egg", "milk"]
    assert merged == ca.merge(cb)


def test_sibling_replica_keeps_both():
    st, p, *_ = _concurrent_setup()
    # 两次写的同步目标都包含 p[0] 和 p[1]，所以它们各自都有两个版本
    assert values(st.replica(p[0], "cart")) == ["egg", "milk"]
    assert values(st.replica(p[1], "cart")) == ["egg", "milk"]


def test_sibling_resolved_by_write_with_merged_context():
    st, p, *_ = _concurrent_setup()
    st.deliver_pending()
    vals, ctx = st.get("cart")
    st.put("cart", "+".join(sorted(vals)), ctx)
    st.deliver_pending()
    vals, _ = st.get("cart")
    assert vals == ["egg+milk"]
    assert all(values(st.replica(x, "cart")) == ["egg+milk"] for x in p)


def test_sibling_write_without_context_creates_another_sibling():
    st = QuorumStore(NODES, n=3, w=3, r=3)
    p = st.preference_list("k")
    st.put("k", "a", coordinator=p[0])
    st.put("k", "b", coordinator=p[1])  # 没带上下文：和 a 并发
    vals, _ = st.get("k")
    assert sorted(vals) == ["a", "b"]


def test_sibling_get_dedupes_equal_versions():
    st = QuorumStore(NODES, n=3, w=3, r=3)
    st.put("k", "v")
    vals, _ = st.get("k")
    assert vals == ["v"]


# =====================================================================
# 读修复与 quorum 失败
# =====================================================================


def test_repair_stale_replica_on_read():
    st = QuorumStore(NODES, n=3, w=2, r=3)
    p = st.preference_list("k")
    st.put("k", "v1")
    st.deliver_pending()
    _, ctx = st.get("k")
    st.set_down(p[0])
    st.set_down(p[2])
    with pytest.raises(QuorumError):
        st.put("k", "v2", ctx)        # 只有 p[1] 在线，W=2 不够
    st.set_up(p[0])
    st.set_up(p[2])
    assert values(st.replica(p[1], "k")) == ["v2"], "失败的写没有回滚，已经落在 p[1] 上了"
    before = st.read_repairs
    vals, _ = st.get("k")
    assert vals == ["v2"], "部分失败的写之后还是被读到了"
    assert st.read_repairs - before == 2
    assert all(values(st.replica(x, "k")) == ["v2"] for x in p)


def test_repair_only_touches_readers():
    st = QuorumStore(NODES, n=3, w=1, r=2)
    p = st.preference_list("k")
    st.set_down(p[0])
    st.set_down(p[1])
    st.put("k", "v")              # 只写到 p[2]
    st.set_up(p[0])
    st.set_up(p[1])
    st.set_down(p[1])
    vals, _ = st.get("k")         # 读 p[0], p[2]
    assert vals == ["v"]
    assert values(st.replica(p[0], "k")) == ["v"]
    assert st.replica(p[1], "k") == [], "没参与读的副本不修"
    assert st.read_repairs == 1


def test_repair_counts_nothing_when_consistent():
    st = QuorumStore(NODES, n=3, w=3, r=3)
    st.put("k", "v")
    st.get("k")
    st.get("missing")
    assert st.read_repairs == 0


def test_repair_merges_siblings_into_replicas():
    st = QuorumStore(NODES, n=3, w=1, r=3)
    p = st.preference_list("k")
    st.put("k", "a", coordinator=p[0])
    st.put("k", "b", coordinator=p[1])
    # 不调用 deliver_pending()，只靠读修复
    vals, _ = st.get("k")
    assert sorted(vals) == ["a", "b"]
    assert all(values(st.replica(x, "k")) == ["a", "b"] for x in p)


def test_quorum_read_fails_when_not_enough_up():
    st = QuorumStore(NODES, n=3, w=2, r=2)
    p = st.preference_list("k")
    st.put("k", "v")
    st.set_down(p[0])
    st.set_down(p[1])
    with pytest.raises(QuorumError):
        st.get("k")


def test_quorum_write_fails_when_all_down():
    st = QuorumStore(NODES, n=3, w=2, r=2)
    for x in st.preference_list("k"):
        st.set_down(x)
    with pytest.raises(QuorumError):
        st.put("k", "v")
