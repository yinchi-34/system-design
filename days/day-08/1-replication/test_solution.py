import importlib.util
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day08_repl_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
ReplicatedStore = _mod.ReplicatedStore
LogEntry = _mod.LogEntry
NodeDownError = _mod.NodeDownError
NotEnoughReplicasError = _mod.NotEnoughReplicasError


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def s(clock):
    return ReplicatedStore(["a", "b", "c"], clock=clock)


def keys_values(store, node, keys):
    return {k: store.read(node, k) for k in keys}


# =====================================================================
# 基本复制
# =====================================================================


def test_basic_initial_state(s):
    assert s.leader == "a"
    assert s.term == 1
    assert s.followers() == ["b", "c"]
    assert all(s.applied_lsn(n) == 0 for n in "abc")


@pytest.mark.parametrize("nodes", [[], ["a", "a"]])
def test_basic_invalid_nodes(nodes):
    with pytest.raises(ValueError):
        ReplicatedStore(nodes)


def test_basic_write_goes_to_leader_only(s, clock):
    assert s.write("x", 1) == 1
    clock.advance(1)
    assert s.write("y", 2) == 2
    assert s.read("a", "x") == 1
    assert s.read("b", "x") is None
    assert s.read("b", "x", "dflt") == "dflt"
    assert s.log("a") == [LogEntry(1, 1, "x", 1, 100.0), LogEntry(1, 2, "y", 2, 101.0)]


def test_basic_sync_applies_in_order(s):
    for i in range(5):
        s.write("k", i)
    assert s.sync("b", max_entries=2) == 2
    assert s.read("b", "k") == 1
    assert s.applied_lsn("b") == 2
    assert s.sync("b") == 3
    assert s.read("b", "k") == 4
    assert s.sync("b") == 0
    assert s.log("b") == s.log("a")


def test_basic_log_returns_copy(s):
    s.write("x", 1)
    s.log("a").clear()
    assert len(s.log("a")) == 1


def test_basic_sync_errors(s):
    with pytest.raises(ValueError):
        s.sync("a")
    s.set_down("b")
    with pytest.raises(NodeDownError):
        s.sync("b")
    with pytest.raises(NodeDownError):
        s.read("b", "x")
    s.set_down("a")
    with pytest.raises(NodeDownError):
        s.write("x", 1)
    with pytest.raises(NodeDownError):
        s.sync("c")


def test_basic_down_node_keeps_data(s):
    s.write("x", 1)
    s.sync("b")
    s.set_down("b")
    s.write("x", 2)
    s.set_up("b")
    assert s.read("b", "x") == 1
    assert s.sync("b") == 1
    assert s.read("b", "x") == 2


# =====================================================================
# 复制延迟
# =====================================================================


def test_lag_entries(s):
    for i in range(4):
        s.write(f"k{i}", i)
    s.sync("b", max_entries=1)
    assert s.lag("a") == 0
    assert s.lag("b") == 3
    assert s.lag("c") == 4


def test_lag_seconds_is_age_of_oldest_unapplied(s, clock):
    s.write("x", 1)          # t=100
    clock.advance(5)
    s.write("y", 2)          # t=105
    clock.advance(10)        # now=115
    assert s.lag_seconds("b") == pytest.approx(15.0)
    s.sync("b", max_entries=1)
    assert s.lag_seconds("b") == pytest.approx(10.0)
    s.sync("b")
    assert s.lag_seconds("b") == 0.0
    assert s.lag_seconds("a") == 0.0


def test_lag_seconds_grows_while_idle(s, clock):
    s.write("x", 1)
    clock.advance(3)
    first = s.lag_seconds("c")
    clock.advance(3)
    assert s.lag_seconds("c") == pytest.approx(first + 3)


# =====================================================================
# 半同步复制
# =====================================================================


def test_semisync_replicates_before_returning(s):
    s.write("x", 1, sync_replicas=1)
    assert s.read("b", "x") == 1
    assert s.read("c", "x") is None
    s.write("y", 2, sync_replicas=2)
    assert s.read("c", "x") == 1 and s.read("c", "y") == 2


def test_semisync_skips_down_followers(s):
    s.set_down("b")
    s.write("x", 1, sync_replicas=1)
    assert s.read("c", "x") == 1


def test_semisync_not_enough_replicas_writes_nothing(s):
    s.set_down("b")
    with pytest.raises(NotEnoughReplicasError):
        s.write("x", 1, sync_replicas=2)
    assert s.applied_lsn("a") == 0
    assert s.read("a", "x") is None


def test_semisync_negative(s):
    with pytest.raises(ValueError):
        s.write("x", 1, sync_replicas=-1)


# =====================================================================
# 故障切换
# =====================================================================


def test_failover_requires_leader_down(s):
    with pytest.raises(ValueError):
        s.failover()


def test_failover_picks_most_up_to_date(s):
    for i in range(5):
        s.write("k", i)
    s.sync("b", max_entries=2)
    s.sync("c", max_entries=4)
    s.set_down("a")
    lost = s.failover()
    assert s.leader == "c"
    assert s.term == 2
    assert lost == 1
    assert s.followers() == ["a", "b"]


def test_failover_tie_breaks_by_order(s):
    s.write("x", 1)
    s.sync("b")
    s.sync("c")
    s.set_down("a")
    assert s.failover() == 0
    assert s.leader == "b"


def test_failover_ignores_down_followers(s):
    s.write("x", 1)
    s.sync("b")
    s.set_down("b")
    s.set_down("a")
    assert s.failover() == 1
    assert s.leader == "c"


def test_failover_no_followers_up(s):
    s.set_down("a")
    s.set_down("b")
    s.set_down("c")
    with pytest.raises(NodeDownError):
        s.failover()


def test_failover_new_leader_continues_lsn_with_new_term(s):
    s.write("x", 1)
    s.write("x", 2)
    s.sync("b", max_entries=1)
    s.set_down("a")
    s.failover()
    assert s.read("b", "x") == 1  # 第 2 条写丢了
    assert s.write("y", 9) == 2
    assert s.log("b")[-1][:4] == (2, 2, "y", 9)
    assert s.sync("c") == 2
    assert s.log("c") == s.log("b")


def test_failover_semisync_loses_nothing(s):
    for i in range(3):
        s.write("k", i, sync_replicas=1)
    s.set_down("a")
    assert s.failover() == 0
    assert s.read("b", "k") == 2


# =====================================================================
# 旧 leader 回归：分叉与截断
# =====================================================================


def test_diverge_old_leader_truncates_and_rejoins(s):
    s.write("x", "x1")
    s.write("y", "y1")
    s.sync("b")
    s.sync("c")
    s.write("x", "x2-lost")   # lsn 3, term 1，只在 a 上
    s.write("z", "z-lost")    # lsn 4, term 1，只在 a 上
    s.set_down("a")
    assert s.failover() == 2
    s.write("w", "w-new")     # lsn 3, term 2
    s.set_up("a")
    assert s.leader == "b"
    applied = s.sync("a")
    assert applied == 1
    assert s.log("a") == s.log("b")
    assert s.read("a", "x") == "x1", "被截掉的写对应的 key 要恢复成截断点的值"
    assert s.read("a", "z") is None, "只在被截掉的日志里出现过的 key 要消失"
    assert s.read("a", "w") == "w-new"


def test_diverge_old_leader_longer_than_new_leader(s):
    s.write("x", 1)
    s.sync("b")
    s.write("x", 2)
    s.write("x", 3)
    s.set_down("a")
    s.failover()              # b 只有 1 条，a 有 3 条
    s.set_up("a")
    assert s.sync("a") == 0
    assert s.applied_lsn("a") == 1
    assert s.read("a", "x") == 1


def test_diverge_same_length_different_term(s):
    s.write("x", 1)
    s.sync("b")
    s.write("x", "old")       # lsn 2 term 1
    s.set_down("a")
    s.failover()
    s.write("x", "new")       # lsn 2 term 2
    s.set_up("a")
    assert s.applied_lsn("a") == s.applied_lsn("b") == 2
    s.sync("a")
    assert s.read("a", "x") == "new"
    assert [e.term for e in s.log("a")] == [1, 2]


def test_diverge_follower_that_is_prefix_is_not_truncated(s):
    s.write("x", 1)
    s.write("x", 2)
    s.sync("c", max_entries=1)
    s.sync("b")
    s.set_down("a")
    s.failover()
    s.write("x", 3)
    assert s.sync("c") == 2  # c 的日志是 b 的前缀，正常追加即可
    assert [e.value for e in s.log("c")] == [1, 2, 3]


def test_diverge_two_failovers(s):
    s.write("k", "t1")
    s.sync("b")
    s.sync("c")
    s.set_down("a")
    s.failover()               # leader b, term 2
    s.write("k", "t2")
    s.sync("c")
    s.set_down("b")
    s.failover()               # leader c, term 3
    s.write("k", "t3")
    s.set_up("a")
    s.set_up("b")
    s.sync("a")
    s.sync("b")
    assert s.term == 3
    assert s.log("a") == s.log("b") == s.log("c")
    assert [e.term for e in s.log("a")] == [1, 2, 3]


# =====================================================================
# 会话：读自己的写 + 单调读
# =====================================================================


def test_session_read_your_writes_falls_back_to_leader(s):
    sess = s.session()
    sess.write("bio", "hello")
    assert sess.read("bio") == "hello"
    assert sess.last_node == "a"


def test_session_uses_follower_once_caught_up(s):
    sess = s.session()
    sess.write("bio", "hello")
    s.sync("c")
    assert sess.read("bio") == "hello"
    assert sess.last_node == "c"
    s.sync("b")
    sess.read("bio")
    assert sess.last_node == "b"


def test_session_fresh_session_reads_follower(s):
    s.write("x", 1)
    sess = s.session()
    assert sess.read("x") is None  # 没写过，可以读到落后的从库
    assert sess.last_node == "b"


def test_session_monotonic_reads(s):
    s.write("x", 1)
    s.write("x", 2)
    s.sync("b", max_entries=1)
    s.sync("c")
    sess = s.session()
    s.set_down("b")
    assert sess.read("x") == 2           # 读到了 c 上的新值
    assert sess.last_node == "c"
    s.set_up("b")
    s.set_down("c")
    assert sess.read("x") == 2, "读到过新值以后，不能再读到落后从库上的旧值"
    assert sess.last_node == "a"


def test_session_skips_down_followers(s):
    sess = s.session()
    sess.write("x", 1)
    s.sync("b")
    s.sync("c")
    s.set_down("b")
    sess.read("x")
    assert sess.last_node == "c"


def test_session_write_with_semisync(s):
    sess = s.session()
    sess.write("x", 1, sync_replicas=1)
    assert sess.read("x") == 1
    assert sess.last_node == "b"
