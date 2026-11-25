import importlib.util
import random
import sys
import time
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day21_scheduler_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
TaskScheduler = _mod.TaskScheduler
Lease = _mod.Lease


class FakeClock:
    def __init__(self, t=1000.0):
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
    return TaskScheduler(clock=clock, lease_seconds=30, max_attempts=3, base_backoff=1, max_backoff=8)


def ids(leases):
    return [l.task_id for l in leases]


# =====================================================================
# 参数与基本流程
# =====================================================================


@pytest.mark.parametrize("kw", [
    dict(lease_seconds=0), dict(max_attempts=0), dict(base_backoff=-1), dict(base_backoff=10, max_backoff=5),
])
def test_invalid_args(kw):
    with pytest.raises(ValueError):
        TaskScheduler(**kw)


def test_backoff(s):
    assert [s.backoff(a) for a in range(1, 7)] == [1, 2, 4, 8, 8, 8]


def test_submit_poll_ack(s):
    assert s.submit("a", {"x": 1}) is True
    assert s.state("a") == "pending"
    [l] = s.poll()
    assert isinstance(l, Lease)
    assert l.task_id == "a" and l.payload == {"x": 1} and l.attempt == 1 and l.token >= 1
    assert s.state("a") == "running"
    assert s.poll() == []
    assert s.ack("a", l.token) is True
    assert s.state("a") == "done"
    assert s.ack("a", l.token) is False


def test_submit_is_idempotent(s):
    assert s.submit("a", 1)
    assert s.submit("a", 2) is False
    assert s.poll()[0].payload == 1
    assert s.submit("a", 3) is False, "已经在跑或者跑完的也不能重新提交"


def test_poll_invalid_n(s):
    with pytest.raises(ValueError):
        s.poll(0)


def test_unknown_task(s):
    with pytest.raises(KeyError):
        s.state("nope")
    assert s.ack("nope", 1) is False
    assert s.cancel("nope") is False


def test_tokens_increase(s):
    for i in range(5):
        s.submit(str(i))
    toks = [l.token for l in s.poll(5)]
    assert toks == sorted(toks) and len(set(toks)) == 5


# =====================================================================
# 延迟与优先级
# =====================================================================


def test_delayed_task_not_ready_until_run_at(s, clock):
    s.submit("later", run_at=1010)
    assert s.poll() == []
    clock.t = 1009.99
    assert s.poll() == []
    clock.t = 1010
    assert ids(s.poll()) == ["later"]


def test_order_priority_then_run_at_then_submission(s, clock):
    s.submit("low-old", run_at=900, priority=0)
    s.submit("high-new", run_at=999, priority=5)
    s.submit("high-old", run_at=950, priority=5)
    s.submit("low-old-2", run_at=900, priority=0)
    s.submit("future", run_at=2000, priority=100)
    assert ids(s.poll(10)) == ["high-old", "high-new", "low-old", "low-old-2"]


def test_poll_n_limits(s):
    for i in range(5):
        s.submit(f"t{i}")
    assert ids(s.poll(2)) == ["t0", "t1"]
    assert ids(s.poll(10)) == ["t2", "t3", "t4"]


def test_high_priority_arrives_later_jumps_queue(s, clock):
    s.submit("a")
    s.submit("b")
    s.poll()
    s.submit("urgent", priority=9)
    assert ids(s.poll()) == ["urgent"]


# =====================================================================
# 失败、重试、退避、死信
# =====================================================================


def test_fail_retries_with_backoff(s, clock):
    s.submit("a")
    l1 = s.poll()[0]
    assert s.fail("a", l1.token) is True
    assert s.state("a") == "pending"
    clock.advance(0.99)
    assert s.poll() == []
    clock.advance(0.01)
    l2 = s.poll()[0]
    assert l2.attempt == 2 and l2.token != l1.token
    s.fail("a", l2.token)
    clock.advance(1.99)
    assert s.poll() == []
    clock.advance(0.01)
    l3 = s.poll()[0]
    assert l3.attempt == 3
    s.fail("a", l3.token)
    assert s.state("a") == "dead", "max_attempts=3 用完了"
    assert s.attempts("a") == 3


def test_fail_without_retry_goes_dead(s):
    s.submit("a")
    l = s.poll()[0]
    assert s.fail("a", l.token, retry=False)
    assert s.state("a") == "dead"


def test_retry_keeps_priority(s, clock):
    s.submit("vip", priority=9)
    l = s.poll()[0]
    s.fail("vip", l.token)
    s.submit("normal")
    clock.advance(1)
    assert ids(s.poll()) == ["vip"]


# =====================================================================
# 租约
# =====================================================================


def test_lease_expiry_reclaims(s, clock):
    s.submit("a")
    l1 = s.poll()[0]
    clock.advance(29.99)
    assert s.state("a") == "running"
    clock.advance(0.01)  # 租约到期，当作一次失败，从到期时刻开始退避 1 秒
    assert s.state("a") == "pending"
    assert s.poll() == []
    clock.advance(1)
    l2 = s.poll()[0]
    assert l2.attempt == 2


def test_stale_worker_cannot_ack(s, clock):
    s.submit("a")
    old = s.poll()[0]
    clock.advance(31)
    new = s.poll()[0]
    assert s.ack("a", old.token) is False, "旧 worker 的令牌已经作废（Day 12 的 fencing token）"
    assert s.fail("a", old.token) is False
    assert s.heartbeat("a", old.token) is False
    assert s.ack("a", new.token) is True


def test_heartbeat_extends_lease(s, clock):
    s.submit("a")
    l = s.poll()[0]
    for _ in range(5):
        clock.advance(20)
        assert s.heartbeat("a", l.token) is True
    assert s.state("a") == "running"
    clock.advance(30)
    assert s.state("a") == "pending"


def test_lease_expiry_counts_towards_max_attempts(s, clock):
    s.submit("a")
    for _ in range(3):
        clock.advance(100)
        assert len(s.poll()) == 1
    clock.advance(30)
    assert s.state("a") == "dead"


def test_ack_after_expiry_fails(s, clock):
    s.submit("a")
    l = s.poll()[0]
    clock.advance(30)
    assert s.ack("a", l.token) is False


# =====================================================================
# 取消、统计、唤醒时间
# =====================================================================


def test_cancel(s, clock):
    s.submit("a", run_at=2000)
    s.submit("b")
    s.submit("c")
    assert s.cancel("a") and s.cancel("b")
    assert s.state("a") == "cancelled"
    [lc] = s.poll(10)
    assert lc.task_id == "c"
    assert s.cancel("c") is False, "已经在跑的不能取消"
    s.ack("c", lc.token)
    clock.t = 3000
    assert s.poll() == []


def test_cancel_pending_retry(s, clock):
    s.submit("a")
    s.fail("a", s.poll()[0].token)
    assert s.cancel("a")
    clock.advance(100)
    assert s.poll() == []


def test_counts(s, clock):
    for i in range(5):
        s.submit(f"t{i}")
    ls = s.poll(3)
    s.ack("t0", ls[0].token)
    s.fail("t1", ls[1].token, retry=False)
    s.cancel("t3")
    assert s.counts() == {"pending": 1, "running": 1, "done": 1, "dead": 1, "cancelled": 1}


def test_next_wakeup(s, clock):
    assert s.next_wakeup() is None
    s.submit("a", run_at=1050)
    assert s.next_wakeup() == 1050
    s.submit("b")
    assert s.next_wakeup() == 1000
    s.poll()  # b 开始跑，租约到 1030
    assert s.next_wakeup() == 1030


# =====================================================================
# 性能：要用堆，不能每次 poll 都扫描全部任务
# =====================================================================


def test_many_tasks_fast():
    clock = FakeClock(0)
    s = TaskScheduler(clock=clock, lease_seconds=10)
    rng = random.Random(5)
    n = 30_000
    for i in range(n):
        s.submit(f"t{i}", run_at=rng.uniform(0, 100), priority=rng.randint(0, 3))
    start = time.perf_counter()
    done = 0
    while clock.t <= 101:
        while True:
            batch = s.poll(50)
            if not batch:
                break
            for l in batch:
                s.ack(l.task_id, l.token)
                done += 1
        clock.advance(0.5)
    assert done == n
    assert time.perf_counter() - start < 3, "30000 个任务应该在 1 秒左右处理完"
