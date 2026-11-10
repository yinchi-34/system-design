import importlib.util
import threading
import time
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day06_id_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
Snowflake = _mod.Snowflake
parse_id = _mod.parse_id
SegmentAllocator = _mod.SegmentAllocator
ClockMovedBackwardsError = _mod.ClockMovedBackwardsError
EPOCH = _mod.DEFAULT_EPOCH_MS

T = EPOCH + 1_000_000  # 测试里用的「现在」


class ScriptedClock:
    """按顺序返回 values 里的值，用完后一直返回最后一个值。"""

    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class StepClock:
    """前 n 次调用返回 t，之后返回 t + 1。"""

    def __init__(self, t, n):
        self.t, self.n, self.calls = t, n, 0

    def __call__(self):
        self.calls += 1
        return self.t if self.calls <= self.n else self.t + 1


# =====================================================================
# Snowflake：布局与基本行为
# =====================================================================


def test_snowflake_bit_layout():
    gen = Snowflake(worker_id=3, datacenter_id=1, clock=ScriptedClock(EPOCH + 1000))
    assert gen.next_id() == (1000 << 22) | (1 << 17) | (3 << 12) | 0
    assert gen.next_id() == (1000 << 22) | (1 << 17) | (3 << 12) | 1


def test_snowflake_parse_roundtrip():
    gen = Snowflake(worker_id=31, datacenter_id=17, clock=ScriptedClock(T))
    for seq in range(5):
        assert parse_id(gen.next_id()) == (T, 17, 31, seq)


def test_snowflake_custom_epoch():
    epoch = 1_600_000_000_000
    gen = Snowflake(worker_id=1, epoch_ms=epoch, clock=ScriptedClock(epoch + 42))
    i = gen.next_id()
    assert i >> 22 == 42
    assert parse_id(i, epoch_ms=epoch).timestamp_ms == epoch + 42


def test_snowflake_sequence_resets_on_new_ms():
    gen = Snowflake(1, clock=ScriptedClock(T, T, T, T + 1, T + 5))
    seqs = [parse_id(gen.next_id()).sequence for _ in range(5)]
    assert seqs == [0, 1, 2, 0, 0]


def test_snowflake_sequence_exhaustion_waits_for_next_ms():
    clock = StepClock(T, 10_000)
    gen = Snowflake(1, clock=clock)
    ids = [gen.next_id() for _ in range(4097)]
    parts = [parse_id(i) for i in ids]
    assert all(p.timestamp_ms == T for p in parts[:4096])
    assert [p.sequence for p in parts[:4096]] == list(range(4096))
    assert parts[4096].timestamp_ms == T + 1, "一毫秒最多 4096 个，用完要等下一毫秒"
    assert parts[4096].sequence == 0
    assert ids == sorted(set(ids))


def test_snowflake_ids_strictly_increasing_real_clock():
    gen = Snowflake(5, 2)
    ids = [gen.next_id() for _ in range(20_000)]
    assert all(a < b for a, b in zip(ids, ids[1:]))


def test_snowflake_real_clock_timestamp_is_now():
    gen = Snowflake(0)
    before = time.time_ns() // 1_000_000
    p = parse_id(gen.next_id())
    after = time.time_ns() // 1_000_000
    assert before <= p.timestamp_ms <= after
    assert gen.next_id() > 0


def test_snowflake_different_workers_never_collide():
    a = Snowflake(1, clock=ScriptedClock(T))
    b = Snowflake(2, clock=ScriptedClock(T))
    ids_a = {a.next_id() for _ in range(1000)}
    ids_b = {b.next_id() for _ in range(1000)}
    assert not ids_a & ids_b


def test_snowflake_thread_safe():
    gen = Snowflake(7, 3)
    out, lock = [], threading.Lock()

    def work():
        local = [gen.next_id() for _ in range(5000)]
        with lock:
            out.extend(local)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 40_000
    assert len(set(out)) == 40_000, "多线程下发出了重复 ID"


@pytest.mark.parametrize("w, d", [(32, 0), (-1, 0), (0, 32), (0, -1)])
def test_snowflake_invalid_ids(w, d):
    with pytest.raises(ValueError):
        Snowflake(w, d)


def test_snowflake_before_epoch():
    gen = Snowflake(1, clock=ScriptedClock(EPOCH - 1))
    with pytest.raises(ValueError):
        gen.next_id()


def test_snowflake_timestamp_overflow():
    ok = Snowflake(1, clock=ScriptedClock(EPOCH + (1 << 41) - 1))
    assert ok.next_id() > 0
    assert ok.next_id() < (1 << 63)
    bad = Snowflake(1, clock=ScriptedClock(EPOCH + (1 << 41)))
    with pytest.raises(OverflowError):
        bad.next_id()


# =====================================================================
# Snowflake：时钟回拨
# =====================================================================


def test_snowflake_small_backward_waits():
    clock = ScriptedClock(T, T - 3, T - 2, T - 1, T, T + 1)
    gen = Snowflake(1, clock=clock)
    first = gen.next_id()
    second = gen.next_id()
    assert second > first
    assert parse_id(second).timestamp_ms >= T
    assert clock.calls >= 5, "小幅回拨应该反复读时钟等它追上"


def test_snowflake_small_backward_at_limit_waits():
    gen = Snowflake(1, clock=ScriptedClock(T, T - 5, T), max_backward_ms=5)
    a = gen.next_id()
    assert gen.next_id() > a


def test_snowflake_large_backward_raises():
    gen = Snowflake(1, clock=ScriptedClock(T, T - 6, T + 1), max_backward_ms=5)
    first = gen.next_id()
    with pytest.raises(ClockMovedBackwardsError):
        gen.next_id()
    # 时钟恢复之后可以继续发号，而且仍然比之前的大
    assert gen.next_id() > first


def test_snowflake_backward_zero_tolerance():
    gen = Snowflake(1, clock=ScriptedClock(T, T - 1), max_backward_ms=0)
    gen.next_id()
    with pytest.raises(ClockMovedBackwardsError):
        gen.next_id()


def test_snowflake_backward_after_sequence_use():
    # 回拨回来后正好落在上次那一毫秒：要接着上次的序列号，而不是从 0 开始
    gen = Snowflake(1, clock=ScriptedClock(T, T, T, T - 2, T - 1, T, T, T + 1))
    ids = [gen.next_id() for _ in range(5)]
    assert len(set(ids)) == 5
    assert ids == sorted(ids)


# =====================================================================
# 号段分配器
# =====================================================================


class FakeDB:
    """模拟 UPDATE id_alloc SET max_id = max_id + step，返回新号段的起点。"""

    def __init__(self, start=0):
        self.max_id = start
        self.fail = False
        self.calls = 0
        self.lock = threading.Lock()

    def fetch(self, step):
        with self.lock:
            self.calls += 1
            if self.fail:
                raise ConnectionError("db down")
            self.max_id += step
            return self.max_id - step + 1


@pytest.mark.parametrize("step, at", [(0, 0.9), (-1, 0.9), (10, 0), (10, 1.1), (10, -0.5)])
def test_segment_invalid_args(step, at):
    with pytest.raises(ValueError):
        SegmentAllocator(FakeDB().fetch, step, prefetch_at=at)


def test_segment_fetches_on_construction():
    db = FakeDB()
    alloc = SegmentAllocator(db.fetch, 10)
    assert alloc.fetch_count == 1
    assert db.max_id == 10


def test_segment_construction_failure_propagates():
    db = FakeDB()
    db.fail = True
    with pytest.raises(ConnectionError):
        SegmentAllocator(db.fetch, 10)


def test_segment_ids_are_sequential():
    alloc = SegmentAllocator(FakeDB().fetch, 10)
    assert [alloc.next_id() for _ in range(35)] == list(range(1, 36))


def test_segment_prefetch_timing():
    alloc = SegmentAllocator(FakeDB().fetch, 10, prefetch_at=0.9)
    counts = []
    for _ in range(21):
        alloc.next_id()
        counts.append(alloc.fetch_count)
    #           1  2  3  4  5  6  7  8  9 10 11 ... 19 20 21
    assert counts == [1] * 8 + [2] * 10 + [3] * 3


def test_segment_prefetch_at_one():
    alloc = SegmentAllocator(FakeDB().fetch, 4, prefetch_at=1.0)
    counts = []
    for _ in range(5):
        alloc.next_id()
        counts.append(alloc.fetch_count)
    assert counts == [1, 1, 1, 2, 2]


def test_segment_prefetch_failure_is_swallowed_until_exhausted():
    db = FakeDB()
    alloc = SegmentAllocator(db.fetch, 10)
    db.fail = True
    assert [alloc.next_id() for _ in range(10)] == list(range(1, 11)), "预取失败不应该影响当前号段"
    with pytest.raises(ConnectionError):
        alloc.next_id()
    db.fail = False
    assert alloc.next_id() == 11
    assert alloc.fetch_count == 2


def test_segment_prefetch_retried_on_next_call():
    db = FakeDB()
    alloc = SegmentAllocator(db.fetch, 10)
    for _ in range(8):
        alloc.next_id()
    db.fail = True
    alloc.next_id()  # 第 9 个：预取失败
    assert alloc.fetch_count == 1
    db.fail = False
    alloc.next_id()  # 第 10 个：再试一次预取
    assert alloc.fetch_count == 2
    assert alloc.next_id() == 11


def test_segment_step_one():
    alloc = SegmentAllocator(FakeDB().fetch, 1)
    assert [alloc.next_id() for _ in range(5)] == [1, 2, 3, 4, 5]


def test_segment_shared_db_trend_increasing():
    db = FakeDB()
    a, b = SegmentAllocator(db.fetch, 5), SegmentAllocator(db.fetch, 5)
    ids_a = [a.next_id() for _ in range(23)]
    ids_b = [b.next_id() for _ in range(17)]
    assert not set(ids_a) & set(ids_b)
    assert ids_a == sorted(ids_a) and ids_b == sorted(ids_b)
    assert ids_a[:5] == [1, 2, 3, 4, 5]
    assert ids_b[:5] == [6, 7, 8, 9, 10]  # 两台机器的号段交错，所以只能「趋势递增」


def test_segment_thread_safe():
    db = FakeDB()
    alloc = SegmentAllocator(db.fetch, 100)
    out, lock = [], threading.Lock()

    def work():
        local = [alloc.next_id() for _ in range(2000)]
        with lock:
            out.extend(local)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == list(range(1, 16_001)), "多线程下号段发重复或跳号了"
    assert alloc.fetch_count == 161
