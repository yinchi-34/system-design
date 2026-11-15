import hashlib
import importlib.util
import math
import random
import sys
import threading
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day13_counters_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
ShardedCounter = _mod.ShardedCounter
BufferedCounter = _mod.BufferedCounter
HyperLogLog = _mod.HyperLogLog


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# =====================================================================
# 分片计数器
# =====================================================================


def test_sharded_basic():
    c = ShardedCounter(4)
    assert c.num_shards == 4
    assert c.get("v") == 0
    for _ in range(10):
        c.increment("v")
    c.increment("v", -3)
    assert c.get("v") == 7
    assert sum(c.shards("v")) == 7
    assert len(c.shards("v")) == 4
    assert c.shards("other") == [0, 0, 0, 0]


def test_sharded_uses_rng_once_per_increment():
    c = ShardedCounter(8, rng=random.Random(42))
    ref = random.Random(42)
    expected = [0] * 8
    for i in range(200):
        shard = c.increment("v", i)
        assert shard == ref.randrange(8)
        expected[shard] += i
    assert c.shards("v") == expected


def test_sharded_spreads_writes():
    c = ShardedCounter(10, rng=random.Random(1))
    for _ in range(10_000):
        c.increment("hot")
    assert all(800 < s < 1200 for s in c.shards("hot"))


def test_sharded_keys_independent():
    c = ShardedCounter(3, rng=random.Random(0))
    c.increment("a", 5)
    c.increment("b", 7)
    assert (c.get("a"), c.get("b")) == (5, 7)


def test_sharded_invalid():
    with pytest.raises(ValueError):
        ShardedCounter(0)
    c = ShardedCounter(2)
    with pytest.raises(TypeError):
        c.increment("v", 1.5)


def test_sharded_thread_safe():
    c = ShardedCounter(8)

    def work():
        for _ in range(5000):
            c.increment("hot")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.get("hot") == 40_000


# =====================================================================
# 缓冲聚合
# =====================================================================


class Sink:
    def __init__(self):
        self.batches = []
        self.fail = False

    def __call__(self, batch):
        if self.fail:
            raise ConnectionError("db down")
        self.batches.append(batch)

    def totals(self):
        out = {}
        for b in self.batches:
            for k, v in b.items():
                out[k] = out.get(k, 0) + v
        return out


def test_buffered_aggregates_until_interval():
    clock, sink = FakeClock(), Sink()
    b = BufferedCounter(sink, flush_interval=1.0, clock=clock)
    for _ in range(100):
        b.increment("a")
    b.increment("b", 5)
    assert sink.batches == []
    assert b.pending("a") == 100
    clock.advance(1.0)
    b.increment("a")
    assert sink.batches == [{"a": 101, "b": 5}], "1 秒内的 102 次增量合并成一次写"
    assert b.pending("a") == 0


def test_buffered_flush_by_max_keys():
    clock, sink = FakeClock(), Sink()
    b = BufferedCounter(sink, flush_interval=60, max_keys=3, clock=clock)
    b.increment("a")
    b.increment("b")
    assert sink.batches == []
    b.increment("c")
    assert sink.batches == [{"a": 1, "b": 1, "c": 1}]


def test_buffered_zero_net_delta_removed():
    clock, sink = FakeClock(), Sink()
    b = BufferedCounter(sink, flush_interval=60, max_keys=2, clock=clock)
    b.increment("a", 1)
    b.increment("a", -1)  # 点赞又取消
    b.increment("b", 1)
    assert sink.batches == [], "净增量为 0 的 key 不占缓冲名额"
    assert b.pending("a") == 0
    assert b.flush() == 1
    assert sink.batches == [{"b": 1}]


def test_buffered_flush_empty_does_not_call_sink():
    sink = Sink()
    b = BufferedCounter(sink, clock=FakeClock())
    assert b.flush() == 0
    assert sink.batches == []


def test_buffered_flush_returns_count_and_passes_copy():
    clock = FakeClock()
    received = []
    b = BufferedCounter(received.append, flush_interval=60, clock=clock)
    b.increment("a", 2)
    b.increment("b", 3)
    assert b.flush() == 2
    received[0]["a"] = 999  # sink 改了收到的字典也不能影响计数器
    b.increment("a", 1)
    assert b.pending("a") == 1


def test_buffered_failure_keeps_data_without_duplicates():
    clock, sink = FakeClock(), Sink()
    b = BufferedCounter(sink, flush_interval=1, clock=clock)
    b.increment("a", 10)
    sink.fail = True
    clock.advance(1)
    b.increment("a", 1)               # 触发 flush，失败，但不能抛给调用方
    assert b.failed_flushes == 1
    assert b.pending("a") == 11
    b.increment("b", 2)               # 失败后还没到下一个间隔，不重试
    assert b.failed_flushes == 1
    with pytest.raises(ConnectionError):
        b.flush()                     # 手动 flush 失败时异常要抛出来
    assert b.failed_flushes == 2
    sink.fail = False
    assert b.flush() == 2
    assert sink.totals() == {"a": 11, "b": 2}
    assert b.flush() == 0


def test_buffered_failure_updates_last_flush():
    clock, sink = FakeClock(), Sink()
    b = BufferedCounter(sink, flush_interval=5, clock=clock)
    sink.fail = True
    clock.advance(5)
    b.increment("a")                  # 失败一次
    for _ in range(4):
        clock.advance(1)
        b.increment("a")
    assert b.failed_flushes == 1, "失败后也要等满一个间隔再试，不能每次都打存储"
    sink.fail = False
    clock.advance(1)
    b.increment("a")
    assert sink.totals() == {"a": 6}


def test_buffered_close_flushes():
    sink = Sink()
    b = BufferedCounter(sink, flush_interval=60, clock=FakeClock())
    b.increment("a", 3)
    assert b.close() == 1
    assert sink.totals() == {"a": 3}


def test_buffered_invalid():
    with pytest.raises(ValueError):
        BufferedCounter(Sink(), flush_interval=0)
    with pytest.raises(ValueError):
        BufferedCounter(Sink(), max_keys=0)
    with pytest.raises(TypeError):
        BufferedCounter(Sink()).increment("a", "1")


def test_buffered_thread_safe_no_loss():
    sink = Sink()
    lock = threading.Lock()

    def safe_sink(batch):
        with lock:
            sink(batch)

    b = BufferedCounter(safe_sink, flush_interval=1e-9, max_keys=5)

    def work(k):
        for i in range(3000):
            b.increment(f"k{(i + k) % 7}")

    threads = [threading.Thread(target=work, args=(k,)) for k in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    b.close()
    assert sum(sink.totals().values()) == 18_000


def test_buffered_sink_called_without_lock():
    clock = FakeClock()
    holder = {}

    def reentrant_sink(batch):
        holder["b"].pending("x")  # 持锁调用 sink 的话，这里会死锁
        holder["b"].increment("late", 1)

    b = BufferedCounter(reentrant_sink, flush_interval=60, clock=clock)
    holder["b"] = b
    b.increment("x", 1)
    assert b.flush() == 1
    assert b.pending("late") == 1


# =====================================================================
# HyperLogLog
# =====================================================================


def _ref_registers(items, p):
    m = 1 << p
    reg = bytearray(m)
    for it in items:
        x = int.from_bytes(hashlib.sha1(it.encode()).digest()[:8], "big")
        b = 64 - p
        idx, w = x >> b, x & ((1 << b) - 1)
        reg[idx] = max(reg[idx], b - w.bit_length() + 1)
    return bytes(reg)


def test_hll_registers_exact():
    items = [f"user-{i}" for i in range(500)]
    h = HyperLogLog(8)
    for it in items:
        h.add(it)
    assert h.registers == _ref_registers(items, 8)


def test_hll_empty():
    h = HyperLogLog(10)
    assert h.count() == 0
    assert h.registers == bytes(1024)


def test_hll_add_return_value():
    h = HyperLogLog(10)
    assert h.add("alice") is True
    assert h.add("alice") is False
    assert h.add(b"alice") is False, "str 按 UTF-8 编码，和 bytes 是同一个元素"


def test_hll_duplicates_dont_count():
    h = HyperLogLog(12)
    for _ in range(50):
        for i in range(1000):
            h.add(f"u{i}")
    assert h.count() == pytest.approx(1000, rel=0.05)


@pytest.mark.parametrize("n", [10, 100, 1000])
def test_hll_small_range_linear_counting(n):
    h = HyperLogLog(14)
    for i in range(n):
        h.add(f"viewer:{i}")
    assert abs(h.count() - n) <= max(2, n * 0.02)


@pytest.mark.parametrize("p, n", [(10, 50_000), (14, 200_000)])
def test_hll_large_range_accuracy(p, n):
    h = HyperLogLog(p)
    for i in range(n):
        h.add(f"viewer:{i}")
    std_err = 1.04 / math.sqrt(1 << p)
    assert abs(h.count() - n) / n < 4 * std_err


def test_hll_merge():
    a, b = HyperLogLog(12), HyperLogLog(12)
    for i in range(30_000):
        a.add(f"u{i}")
    for i in range(20_000, 50_000):
        b.add(f"u{i}")
    before = a.registers
    m = a.merge(b)
    assert a.registers == before, "merge 不能修改输入"
    assert m.registers == bytes(max(x, y) for x, y in zip(a.registers, b.registers))
    assert m.count() == pytest.approx(50_000, rel=0.06)


def test_hll_merge_equals_adding_all():
    a, b, both = HyperLogLog(10), HyperLogLog(10), HyperLogLog(10)
    for i in range(3000):
        (a if i % 2 else b).add(str(i))
        both.add(str(i))
    assert a.merge(b).registers == both.registers


def test_hll_invalid():
    for p in (3, 17):
        with pytest.raises(ValueError):
            HyperLogLog(p)
    with pytest.raises(ValueError):
        HyperLogLog(10).merge(HyperLogLog(11))
    with pytest.raises(TypeError):
        HyperLogLog(10).add(42)
