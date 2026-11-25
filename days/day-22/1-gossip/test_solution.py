import importlib.util
import math
import random
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day22_gossip_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
GossipNode = _mod.GossipNode
GossipCluster = _mod.GossipCluster


class FakeClock:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


def node(clock, nid="a", fail=10, cleanup=20, seed=0):
    return GossipNode(nid, clock=clock, fail_timeout=fail, cleanup_timeout=cleanup, rng=random.Random(seed))


# =====================================================================
# 单个节点
# =====================================================================


def test_node_invalid():
    c = FakeClock()
    with pytest.raises(ValueError):
        node(c, fail=0)
    with pytest.raises(ValueError):
        node(c, cleanup=-1)
    node(c, cleanup=0)


def test_node_initial_state():
    n = node(FakeClock())
    assert n.heartbeat == 0
    assert n.digest() == {"a": 0}
    assert n.alive_members() == ["a"] and n.dead_members() == []
    assert n.status("a") == "alive" and n.status("b") is None
    assert n.pick_peers(3) == []


def test_node_tick_increments_heartbeat():
    c = FakeClock()
    n = node(c)
    for t in range(1, 4):
        c.t = t
        n.tick()
    assert n.heartbeat == 3 and n.digest()["a"] == 3


def test_merge_adds_and_updates():
    c = FakeClock()
    n = node(c)
    assert n.merge({"b": 5, "c": 0}) == 2
    assert n.alive_members() == ["a", "b", "c"]
    assert n.merge({"b": 5}) == 0, "心跳没变大，不算新消息"
    assert n.merge({"b": 4}) == 0
    assert n.digest()["b"] == 5
    assert n.merge({"b": 6, "c": 1}) == 2


def test_merge_ignores_self():
    n = node(FakeClock())
    assert n.merge({"a": 100}) == 0
    assert n.heartbeat == 0, "别人对我的看法不能改我自己的心跳"


def test_failure_detection_timeout():
    c = FakeClock()
    n = node(c, fail=10, cleanup=20)
    n.merge({"b": 1})  # t=0 时最后一次听到 b
    c.t = 9
    n.tick()
    assert n.status("b") == "alive"
    c.t = 10
    n.tick()
    assert n.status("b") == "dead"
    assert n.alive_members() == ["a"] and n.dead_members() == ["b"]
    assert "b" not in n.digest(), "死掉的成员不再传播"


def test_fresh_heartbeat_resets_timer():
    c = FakeClock()
    n = node(c, fail=10)
    n.merge({"b": 1})
    c.t = 8
    n.merge({"b": 2})
    c.t = 15
    n.tick()
    assert n.status("b") == "alive"
    c.t = 18
    n.tick()
    assert n.status("b") == "dead"


def test_cleanup_after_dead():
    c = FakeClock()
    n = node(c, fail=10, cleanup=20)
    n.merge({"b": 1})
    c.t = 29
    n.tick()
    assert n.status("b") == "dead"
    c.t = 30
    n.tick()
    assert n.status("b") is None


def test_dead_member_ignores_stale_gossip():
    """别的节点还没发现 b 死了，又把 b 的旧心跳传过来，不能把 b 救活。"""
    c = FakeClock()
    n = node(c)
    n.merge({"b": 7})
    c.t = 10
    n.tick()
    assert n.merge({"b": 7}) == 0
    assert n.status("b") == "dead"


def test_dead_member_revived_by_higher_heartbeat():
    c = FakeClock()
    n = node(c)
    n.merge({"b": 7})
    c.t = 10
    n.tick()
    assert n.merge({"b": 8}) == 1
    assert n.status("b") == "alive"
    c.t = 19
    n.tick()
    assert n.status("b") == "alive", "计时从收到新心跳的那一刻重新开始"


def test_pick_peers_alive_only_and_deterministic():
    c = FakeClock()
    a, b = node(c, seed=42), node(c, seed=42)
    for x in (a, b):
        x.merge({f"p{i}": 1 for i in range(10)})
    pa = a.pick_peers(3)
    assert pa == b.pick_peers(3), "同样的种子，同样的选择（要先排序再 sample）"
    assert len(pa) == 3 and len(set(pa)) == 3 and "a" not in pa
    c.t = 10
    a.tick()
    assert a.pick_peers(3) == []
    assert len(node(c).pick_peers(0)) == 0


# =====================================================================
# 集群模拟
# =====================================================================


def test_cluster_invalid():
    for kw in (dict(n=0), dict(n=3, fanout=0), dict(n=3, drop_rate=1.0), dict(n=3, drop_rate=-0.1)):
        n = kw.pop("n")
        with pytest.raises(ValueError):
            GossipCluster(n, **kw)


def test_cluster_initial_knowledge():
    cl = GossipCluster(4)
    assert cl.ids == ["n0", "n1", "n2", "n3"]
    assert cl.nodes["n0"].alive_members() == ["n0"]
    assert cl.nodes["n3"].alive_members() == ["n0", "n3"]
    assert cl.time == 0 and cl.messages == 0


def test_cluster_step_advances_time_and_heartbeats():
    cl = GossipCluster(3, fanout=1)
    cl.step()
    assert cl.time == 1
    assert all(cl.nodes[i].heartbeat == 1 for i in cl.ids)


def test_cluster_converges_fast():
    cl = GossipCluster(64, fanout=2, fail_timeout=30, seed=1)
    r = cl.run_until(cl.converged, 60)
    assert r is not None
    assert r <= 4 * math.log2(64), f"gossip 应该在 O(log n) 轮内收敛，实际 {r} 轮"


def test_cluster_converges_with_message_loss():
    cl = GossipCluster(32, fanout=3, fail_timeout=30, drop_rate=0.3, seed=2)
    assert cl.run_until(cl.converged, 60) is not None


def test_cluster_no_false_positives_under_loss():
    cl = GossipCluster(20, fanout=3, fail_timeout=10, drop_rate=0.3, seed=3)
    cl.run_until(cl.converged, 60)
    for _ in range(200):
        cl.step()
        for i in cl.ids:
            assert cl.nodes[i].dead_members() == [], "活着的节点不能被误判死亡"


def test_cluster_detects_failure():
    cl = GossipCluster(16, fanout=2, fail_timeout=10, cleanup_timeout=20, seed=4)
    cl.run_until(cl.converged, 60)
    cl.kill("n5")
    t0 = cl.time
    r = cl.run_until(lambda: all("n5" not in cl.nodes[i].alive_members() for i in cl.ids if i != "n5"), 50)
    assert r is not None
    assert cl.time - t0 >= 10, "超时之前不能判死"
    assert cl.time - t0 <= 10 + 8, "所有节点都应该在超时后不久发现"
    assert cl.converged()


def test_cluster_cleanup_and_no_resurrection():
    cl = GossipCluster(16, fanout=2, fail_timeout=10, cleanup_timeout=20, seed=5)
    cl.run_until(cl.converged, 60)
    cl.kill("n7")
    assert cl.run_until(cl.converged, 30) is not None
    for _ in range(60):
        cl.step()
        assert cl.converged(), "死节点一旦被判死，就不能被旧消息救活"
    assert all(cl.nodes[i].status("n7") is None for i in cl.ids if i != "n7")


def test_cluster_down_node_is_frozen():
    cl = GossipCluster(4, seed=6)
    cl.run_until(cl.converged, 30)
    cl.kill("n2")
    hb = cl.nodes["n2"].heartbeat
    m = cl.nodes["n2"].alive_members()
    for _ in range(5):
        cl.step()
    assert cl.nodes["n2"].heartbeat == hb, "挂掉的节点不 tick"
    assert cl.nodes["n2"].alive_members() == m, "也收不到消息"


def test_cluster_partition_and_heal():
    cl = GossipCluster(10, fanout=2, fail_timeout=10, cleanup_timeout=100, seed=7)
    cl.run_until(cl.converged, 60)
    left, right = cl.ids[:5], cl.ids[5:]
    cl.partition(left, right)
    assert not cl.reachable("n0", "n9") and cl.reachable("n0", "n4")
    r = cl.run_until(cl.converged, 40)
    assert r is not None and r >= 10
    assert cl.nodes["n0"].alive_members() == sorted(left)
    assert cl.nodes["n9"].dead_members() == sorted(left)
    cl.heal()
    assert cl.reachable("n0", "n9")
    # 分区期间双方都把对方判死了，选 peer 时只选活着的，所以两边不会再互相发消息
    for _ in range(20):
        cl.step()
    assert cl.nodes["n0"].alive_members() == sorted(left), "这就是为什么真实系统要定期联系种子节点或已死节点"


def test_cluster_message_count():
    cl = GossipCluster(8, fanout=2, seed=8)
    cl.run_until(cl.converged, 30)
    before = cl.messages
    cl.step()
    assert cl.messages - before == 8 * 2, "每个节点每轮发 fanout 条（丢包和不可达的也算发出去了）"
