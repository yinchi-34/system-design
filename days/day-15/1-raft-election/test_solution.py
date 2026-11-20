import heapq
import importlib.util
import itertools
import random
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day15_raft_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
RaftNode = _mod.RaftNode
Message = _mod.Message
FOLLOWER, CANDIDATE, LEADER = _mod.FOLLOWER, _mod.CANDIDATE, _mod.LEADER
REQUEST_VOTE, VOTE_RESPONSE = _mod.REQUEST_VOTE, _mod.VOTE_RESPONSE
APPEND_ENTRIES, APPEND_RESPONSE = _mod.APPEND_ENTRIES, _mod.APPEND_RESPONSE


class Net:
    """模拟网络：固定步长推进时间，消息按延迟投递，支持宕机、分区、丢包。"""

    def __init__(self, timeouts, *, hb=1.0, delay=0.1, logs=None, rng=None, drop=0.0, jitter=0.0):
        ids = list(timeouts)
        logs = logs or {}
        self.nodes = {
            i: RaftNode(i, ids, election_timeout=timeouts[i], heartbeat_interval=hb, log_terms=logs.get(i))
            for i in ids
        }
        self.now = 0.0
        self.delay, self.drop, self.jitter = delay, drop, jitter
        self.rng = rng or random.Random(0)
        self.queue = []
        self.seq = itertools.count()
        self.down = set()
        self.groups = None
        self.leaders_by_term = {}

    def connected(self, a, b):
        if self.groups is None:
            return True
        return any(a in g and b in g for g in self.groups)

    def send(self, msgs):
        for m in msgs:
            if self.drop and self.rng.random() < self.drop:
                continue
            d = self.delay + (self.rng.uniform(0, self.jitter) if self.jitter else 0)
            heapq.heappush(self.queue, (self.now + d, next(self.seq), m))

    def observe(self):
        for i, n in self.nodes.items():
            if i not in self.down and n.state == LEADER:
                self.leaders_by_term.setdefault(n.current_term, set()).add(i)

    def step(self, dt=0.1):
        self.now = round(self.now + dt, 6)
        while self.queue and self.queue[0][0] <= self.now + 1e-9:
            _, _, m = heapq.heappop(self.queue)
            if m.dst in self.down or m.src in self.down or not self.connected(m.src, m.dst):
                continue
            self.send(self.nodes[m.dst].receive(m, self.now))
            self.observe()
        for i, n in self.nodes.items():
            if i not in self.down:
                self.send(n.tick(self.now))
                self.observe()

    def run(self, seconds, dt=0.1):
        for _ in range(int(round(seconds / dt))):
            self.step(dt)

    def leaders(self):
        return sorted(i for i, n in self.nodes.items() if i not in self.down and n.state == LEADER)

    def assert_safe(self):
        for term, ids in self.leaders_by_term.items():
            assert len(ids) <= 1, f"任期 {term} 出现了多个 leader：{ids}"


# =====================================================================
# 单个节点的基本行为
# =====================================================================


def test_basic_initial_state():
    n = RaftNode("a", ["a", "b", "c"], election_timeout=3)
    assert (n.state, n.current_term, n.voted_for, n.leader_id) == (FOLLOWER, 0, None, None)
    assert RaftNode("x", ["x"], election_timeout=1, log_terms=[1, 1, 4]).current_term == 4


def test_basic_invalid_args():
    with pytest.raises(ValueError):
        RaftNode("a", ["a", "b"], election_timeout=0)
    with pytest.raises(ValueError):
        RaftNode("a", ["a", "b"], election_timeout=1, heartbeat_interval=0)


def test_basic_no_election_before_timeout():
    n = RaftNode("a", ["a", "b", "c"], election_timeout=3)
    assert n.tick(2.99) == []
    assert n.state == FOLLOWER


def test_basic_timeout_starts_election():
    n = RaftNode("a", ["a", "b", "c"], election_timeout=3, log_terms=[1, 2])
    msgs = n.tick(3.0)
    assert n.state == CANDIDATE and n.current_term == 3 and n.voted_for == "a"
    assert sorted(m.dst for m in msgs) == ["b", "c"]
    for m in msgs:
        assert (m.kind, m.src, m.term, m.last_log_index, m.last_log_term) == (REQUEST_VOTE, "a", 3, 2, 2)


def test_basic_single_node_becomes_leader():
    n = RaftNode("solo", ["solo"], election_timeout=1)
    assert n.tick(1.0) == []
    assert n.state == LEADER and n.leader_id == "solo" and n.current_term == 1


# =====================================================================
# 投票
# =====================================================================


def rv(src, dst, term, li=0, lt=0):
    return Message(REQUEST_VOTE, src, dst, term, last_log_index=li, last_log_term=lt)


def test_vote_granted_once_per_term():
    n = RaftNode("c", ["a", "b", "c"], election_timeout=5)
    [r1] = n.receive(rv("a", "c", 1), 1.0)
    assert r1 == Message(VOTE_RESPONSE, "c", "a", 1, granted=True)
    [r2] = n.receive(rv("b", "c", 1), 1.1)
    assert r2.granted is False, "同一任期只能投一票"
    [r3] = n.receive(rv("a", "c", 1), 1.2)
    assert r3.granted is True, "同一个候选人重复要票可以再给"
    [r4] = n.receive(rv("b", "c", 2), 1.3)
    assert r4.granted is True and n.current_term == 2, "新任期可以重新投票"


def test_vote_rejects_stale_term():
    n = RaftNode("c", ["a", "b", "c"], election_timeout=5, log_terms=[3])
    [r] = n.receive(rv("a", "c", 2, 5, 2), 1.0)
    assert r.granted is False and r.term == 3


@pytest.mark.parametrize(
    "voter_log, cand_li, cand_lt, granted",
    [
        ([1, 1, 2], 3, 2, True),    # 一样新
        ([1, 1, 2], 5, 2, True),    # 任期相同，更长
        ([1, 1, 2], 2, 2, False),   # 任期相同，更短
        ([1, 1, 2], 9, 1, False),   # 更长但最后任期更旧
        ([1, 1, 2], 1, 3, True),    # 更短但最后任期更新
        ([], 0, 0, True),
    ],
)
def test_vote_election_restriction(voter_log, cand_li, cand_lt, granted):
    n = RaftNode("v", ["c", "v", "x"], election_timeout=5, log_terms=voter_log)
    [r] = n.receive(rv("c", "v", 10, cand_li, cand_lt), 1.0)
    assert r.granted is granted
    assert n.current_term == 10, "任期更大的拉票，即使不投给它也要更新任期"


def test_vote_granting_resets_election_timer():
    n = RaftNode("c", ["a", "b", "c"], election_timeout=3)
    n.receive(rv("a", "c", 1), 2.5)
    assert n.tick(4.0) == [], "刚投完票，计时器从 2.5 重新算"
    assert n.tick(5.5) != []


def test_vote_higher_term_makes_leader_step_down():
    net = Net({"a": 2, "b": 5, "c": 5})
    net.run(3)
    a = net.nodes["a"]
    assert a.state == LEADER
    a.receive(rv("b", "a", a.current_term + 1, 0, 0), net.now)
    assert a.state == FOLLOWER and a.leader_id is None


def test_vote_response_ignored_unless_candidate_same_term():
    n = RaftNode("a", ["a", "b", "c", "d", "e"], election_timeout=1)
    n.tick(1.0)  # term 1 候选人
    assert n.receive(Message(VOTE_RESPONSE, "b", "a", 1, granted=False), 1.1) == []
    n.receive(Message(VOTE_RESPONSE, "b", "a", 1, granted=True), 1.2)
    n.receive(Message(VOTE_RESPONSE, "b", "a", 1, granted=True), 1.3)  # 重复的票不能算两次
    assert n.state == CANDIDATE
    msgs = n.receive(Message(VOTE_RESPONSE, "c", "a", 1, granted=True), 1.4)
    assert n.state == LEADER
    assert sorted(m.dst for m in msgs if m.kind == APPEND_ENTRIES) == ["b", "c", "d", "e"]


# =====================================================================
# 选举（多节点）
# =====================================================================


def test_election_fastest_timeout_wins():
    net = Net({"a": 3, "b": 2, "c": 4})
    net.run(3)
    assert net.leaders() == ["b"]
    for n in net.nodes.values():
        assert n.current_term == 1 and n.leader_id == "b"
    net.assert_safe()


def test_election_leader_crash_triggers_new_election():
    net = Net({"a": 3, "b": 2, "c": 4})
    net.run(3)
    net.down.add("b")
    net.run(6)
    assert net.leaders() == ["a"]
    assert net.nodes["a"].current_term == 2
    net.assert_safe()


def test_election_split_vote_then_recovers():
    ids = ["a", "b", "c", "d"]
    nodes = {i: RaftNode(i, ids, election_timeout=t) for i, t in zip(ids, [2, 2.5, 9, 9])}
    a, b, c, d = (nodes[i] for i in ids)
    ra = {m.dst: m for m in a.tick(2.0)}
    rb = {m.dst: m for m in b.tick(2.5)}
    # c 先收到 a 的拉票，d 先收到 b 的拉票：票被瓜分
    replies = []
    replies += c.receive(ra["c"], 2.6) + d.receive(rb["d"], 2.6)
    replies += c.receive(rb["c"], 2.7) + d.receive(ra["d"], 2.7)
    replies += b.receive(ra["b"], 2.7) + a.receive(rb["a"], 2.7)
    for m in replies:
        nodes[m.dst].receive(m, 2.8)
    assert a.state == CANDIDATE and b.state == CANDIDATE, "4 个节点里 2 票不过半"
    assert c.voted_for == "a" and d.voted_for == "b"
    # a 的这一轮选举超时，任期 +1 再来一次；这次没人和它抢
    msgs = a.tick(4.0)
    assert a.current_term == 2
    while msgs:
        m = msgs.pop(0)
        msgs += nodes[m.dst].receive(m, 4.1)
    assert a.state == LEADER and a.current_term == 2
    assert all(n.leader_id == "a" for n in (b, c, d))


def test_election_stale_log_cannot_win():
    # a 超时最快，但日志落后，c、d、e 不会投给它
    logs = {"a": [1], "b": [1, 1], "c": [1, 1], "d": [1, 1], "e": [1, 1]}
    net = Net({"a": 2, "b": 5, "c": 7, "d": 7.5, "e": 8}, logs=logs)
    net.run(15)
    assert net.leaders() == ["b"]
    net.assert_safe()


# =====================================================================
# 心跳
# =====================================================================


def test_heartbeat_suppresses_elections():
    net = Net({"a": 2, "b": 3, "c": 3.5}, hb=0.5)
    net.run(3)
    term = net.nodes["a"].current_term
    net.run(30)
    assert net.leaders() == ["a"]
    assert all(n.current_term == term for n in net.nodes.values()), "有心跳就不应该再选举"


def test_heartbeat_interval():
    n = RaftNode("solo", ["solo", "x"], election_timeout=1, heartbeat_interval=2)
    n.tick(1.0)
    n.receive(Message(VOTE_RESPONSE, "x", "solo", 1, granted=True), 1.0)
    assert n.tick(2.9) == []
    hb = n.tick(3.0)
    assert hb == [Message(APPEND_ENTRIES, "solo", "x", 1)]


def test_heartbeat_candidate_steps_down_for_same_term_leader():
    n = RaftNode("c", ["a", "b", "c"], election_timeout=1)
    n.tick(1.0)
    assert n.state == CANDIDATE
    [r] = n.receive(Message(APPEND_ENTRIES, "a", "c", 1), 1.2)
    assert n.state == FOLLOWER and n.leader_id == "a"
    assert r == Message(APPEND_RESPONSE, "c", "a", 1, success=True)


def test_heartbeat_stale_term_rejected_and_timer_not_reset():
    n = RaftNode("c", ["a", "b", "c"], election_timeout=3, log_terms=[5])
    [r] = n.receive(Message(APPEND_ENTRIES, "a", "c", 4), 2.9)
    assert r.success is False and r.term == 5
    assert n.leader_id is None
    assert n.tick(3.0) != [], "过时 leader 的心跳不能重置计时器"


# =====================================================================
# 网络分区
# =====================================================================


def test_partition_minority_leader_and_heal():
    net = Net({"a": 2, "b": 4, "c": 4.5, "d": 5, "e": 5.5})
    net.run(3)
    assert net.leaders() == ["a"]
    net.groups = [{"a", "b"}, {"c", "d", "e"}]
    net.run(10)
    # 多数派一侧选出了新 leader；旧 leader 在少数派一侧，还以为自己是 leader（但它的任期旧）
    majority_leaders = [i for i in net.leaders() if i in {"c", "d", "e"}]
    assert len(majority_leaders) == 1
    new = net.nodes[majority_leaders[0]]
    assert new.current_term > net.nodes["a"].current_term
    net.groups = None
    net.run(5)
    assert net.leaders() == majority_leaders, "分区恢复后旧 leader 要让位"
    assert net.nodes["a"].leader_id == majority_leaders[0]
    net.assert_safe()


def test_partition_minority_cannot_elect():
    net = Net({"a": 2, "b": 3, "c": 3.5, "d": 4, "e": 4.5})
    net.run(2.5)
    net.down.add("a")
    net.groups = [{"b"}, {"c", "d", "e"}]
    net.run(10)
    assert net.nodes["b"].state != LEADER, "单独一个节点凑不够过半"
    assert net.nodes["b"].current_term >= 2, "它会不停超时、不停把任期加 1"
    net.assert_safe()


# =====================================================================
# 安全性：随机网络下同一任期最多一个 leader
# =====================================================================


@pytest.mark.parametrize("seed", range(5))
def test_safety_random_network(seed):
    rnd = random.Random(seed)
    timeouts = {f"n{i}": rnd.uniform(1.5, 3.0) for i in range(5)}
    net = Net(timeouts, hb=0.5, delay=0.05, jitter=0.6, drop=0.15, rng=rnd)
    for _ in range(6):
        victim = rnd.choice(sorted(timeouts))
        net.down = {victim}
        net.run(8)
        net.down = set()
        net.run(4)
    net.assert_safe()
    assert net.leaders_by_term, "随机网络下也应该能选出 leader"
