import importlib.util
import time
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "day03_rate_limiter_solution", Path(__file__).with_name("solution.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
TokenBucket = _mod.TokenBucket
SlidingWindowLog = _mod.SlidingWindowLog
SlidingWindowCounter = _mod.SlidingWindowCounter


class FakeClock:
    """假时钟：从 1000 开始，只有调用 advance / set 才会走。"""

    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    def set(self, t):
        self.now = float(t)


def drain(limiter, max_tries=10_000):
    """连续调用 allow() 直到被拒绝，返回成功的次数。"""
    n = 0
    while limiter.allow():
        n += 1
        assert n < max_tries, "allow() 一直返回 True，限流没生效"
    return n


# =====================================================================
# 令牌桶 TokenBucket
# =====================================================================

# ---------- 参数校验 ----------


@pytest.mark.parametrize("capacity, rate", [(0, 1), (-1, 1), (5, 0), (5, -2)])
def test_bucket_invalid_args(capacity, rate):
    with pytest.raises(ValueError):
        TokenBucket(capacity, rate, clock=FakeClock())


@pytest.mark.parametrize("cost", [0, -1, 11])
def test_bucket_invalid_cost(cost):
    b = TokenBucket(10, 1, clock=FakeClock())
    with pytest.raises(ValueError):
        b.allow(cost)
    with pytest.raises(ValueError):
        b.retry_after(cost)


# ---------- 基本行为 ----------


def test_bucket_starts_full_and_allows_burst():
    b = TokenBucket(5, 1, clock=FakeClock())
    assert b.tokens == 5
    assert drain(b) == 5
    assert b.tokens == 0


def test_bucket_refills_over_time():
    clock = FakeClock()
    b = TokenBucket(5, 2, clock=clock)  # 每秒补 2 个
    drain(b)
    clock.advance(0.5)
    assert b.tokens == 1
    assert b.allow() is True
    assert b.allow() is False
    clock.advance(1.0)
    assert b.tokens == 2


def test_bucket_never_exceeds_capacity():
    clock = FakeClock()
    b = TokenBucket(5, 2, clock=clock)
    b.allow()
    clock.advance(3600)  # 一小时没请求
    assert b.tokens == 5
    assert drain(b) == 5


def test_bucket_rejection_does_not_consume():
    clock = FakeClock()
    b = TokenBucket(5, 1, clock=clock)
    drain(b)
    clock.advance(0.5)
    for _ in range(100):
        assert b.allow() is False
    assert b.tokens == 0.5
    clock.advance(0.5)
    assert b.allow() is True


def test_bucket_cost():
    clock = FakeClock()
    b = TokenBucket(10, 1, clock=clock)
    assert b.allow(4) is True
    assert b.allow(4) is True
    assert b.tokens == 2
    assert b.allow(3) is False  # 不够 3 个，不能先扣掉 2 个
    assert b.tokens == 2
    assert b.allow(2) is True
    assert b.allow(10) is False
    clock.advance(10)
    assert b.allow(10) is True  # cost 等于容量是合法的


def test_bucket_fractional_tokens():
    clock = FakeClock()
    b = TokenBucket(1, 0.5, clock=clock)  # 每 2 秒 1 个
    assert b.allow() is True
    clock.advance(1.5)
    assert b.tokens == 0.75
    assert b.allow() is False
    clock.advance(0.5)
    assert b.allow() is True


def test_bucket_lazy_refill_uses_injected_clock():
    """没有后台线程：真实时间过去不影响结果，只看注入的 clock。"""
    clock = FakeClock()
    b = TokenBucket(2, 1000, clock=clock)
    drain(b)
    time.sleep(0.01)
    assert b.allow() is False


def test_bucket_clock_going_backwards():
    clock = FakeClock()
    b = TokenBucket(5, 1, clock=clock)
    drain(b)
    clock.advance(-10)  # 时钟回拨：不能补出负数令牌，也不能崩
    assert b.tokens == 0
    assert b.allow() is False
    clock.set(1001)  # 回到 1000 之后 1 秒
    assert b.allow() is True


def test_bucket_long_run_rate():
    """长期来看，通过的请求数 ≈ 容量 + 速率 × 时间。"""
    clock = FakeClock()
    b = TokenBucket(10, 5, clock=clock)
    passed = 0
    for _ in range(100 * 20):  # 100 秒，每 0.05 秒来一个请求（20 QPS）
        if b.allow():
            passed += 1
        clock.advance(0.05)
    assert 10 + 5 * 100 - 2 <= passed <= 10 + 5 * 100


# ---------- retry_after ----------


def test_bucket_retry_after():
    clock = FakeClock()
    b = TokenBucket(5, 2, clock=clock)
    assert b.retry_after() == 0
    drain(b)
    assert b.retry_after() == 0.5
    assert b.retry_after(3) == 1.5
    clock.advance(0.25)
    assert b.retry_after() == 0.25
    clock.advance(0.25)
    assert b.retry_after() == 0
    assert b.allow() is True


def test_bucket_retry_after_does_not_consume():
    clock = FakeClock()
    b = TokenBucket(3, 1, clock=clock)
    for _ in range(10):
        b.retry_after()
    assert b.tokens == 3


# =====================================================================
# 滑动窗口日志 SlidingWindowLog
# =====================================================================


@pytest.mark.parametrize("limit, window", [(0, 1), (-1, 1), (5, 0), (5, -1)])
def test_log_invalid_args(limit, window):
    with pytest.raises(ValueError):
        SlidingWindowLog(limit, window, clock=FakeClock())


def test_log_basic_limit():
    clock = FakeClock()
    w = SlidingWindowLog(3, 10, clock=clock)
    assert drain(w) == 3
    assert len(w) == 3


def test_log_window_boundary():
    """时刻 t 的请求，在 t + window 那一刻刚好过期（窗口是 (now - window, now]）。"""
    clock = FakeClock()
    w = SlidingWindowLog(1, 10, clock=clock)
    assert w.allow() is True
    clock.advance(9.999)
    assert w.allow() is False
    clock.set(1010)
    assert w.allow() is True


def test_log_slides_one_by_one():
    clock = FakeClock()
    w = SlidingWindowLog(3, 10, clock=clock)
    for _ in range(3):  # t = 1000, 1001, 1002
        assert w.allow() is True
        clock.advance(1)
    assert w.allow() is False  # t = 1003
    clock.set(1010)  # 1000 那条过期
    assert w.allow() is True
    assert w.allow() is False
    clock.set(1011)  # 1001 那条过期
    assert w.allow() is True
    assert w.allow() is False


def test_log_rejected_requests_not_recorded():
    """被拒绝的请求不算数，否则疯狂重试的客户端会永远被锁死。"""
    clock = FakeClock()
    w = SlidingWindowLog(2, 10, clock=clock)
    drain(w)
    for _ in range(50):
        clock.advance(0.1)
        assert w.allow() is False
    clock.set(1010)
    assert drain(w) == 2


def test_log_no_boundary_burst():
    """固定窗口的经典问题：窗口交界处能放过 2 倍流量。滑动窗口日志不允许。"""
    clock = FakeClock()
    w = SlidingWindowLog(10, 10, clock=clock)
    clock.set(1009.5)
    assert drain(w) == 10
    clock.set(1010.5)  # 换了一个「固定窗口」，但过去 10 秒里已经有 10 个了
    assert w.allow() is False
    clock.set(1019.5)
    assert drain(w) == 10


def test_log_retry_after():
    clock = FakeClock()
    w = SlidingWindowLog(2, 10, clock=clock)
    assert w.retry_after() == 0
    w.allow()  # 1000
    clock.set(1004)
    w.allow()  # 1004
    clock.set(1005)
    assert w.retry_after() == 5  # 等 1000 那条在 1010 过期
    clock.set(1010)
    assert w.retry_after() == 0
    w.allow()  # 1010
    assert w.retry_after() == 4  # 等 1004 那条在 1014 过期


def test_log_memory_bounded():
    """日志里最多只保留 limit 条，不能把被拒绝的或已过期的都攒着。"""
    clock = FakeClock()
    w = SlidingWindowLog(5, 1, clock=clock)
    for _ in range(100_000):
        w.allow()
        clock.advance(0.001)
    assert len(w) <= 5
    internal = [v for v in vars(w).values() if hasattr(v, "__len__") and not isinstance(v, str)]
    assert all(len(v) <= 5 for v in internal), "内部存储超过了 limit 条"


def test_log_performance():
    clock = FakeClock()
    w = SlidingWindowLog(1000, 1, clock=clock)
    start = time.perf_counter()
    for _ in range(200_000):
        w.allow()
        clock.advance(0.0005)
    assert time.perf_counter() - start < 2.0, "太慢了，是不是每次都线性扫描或者用了 list.pop(0)？"


# =====================================================================
# 滑动窗口计数 SlidingWindowCounter
# =====================================================================
# 固定窗口按 window 的整数倍对齐：时刻 t 落在第 floor(t / window) 个窗口。
# 估算值 = 上一窗口计数 × (1 - 当前窗口已过去的比例) + 当前窗口计数


@pytest.mark.parametrize("limit, window", [(0, 1), (-1, 1), (5, 0), (5, -1)])
def test_counter_invalid_args(limit, window):
    with pytest.raises(ValueError):
        SlidingWindowCounter(limit, window, clock=FakeClock())


def test_counter_basic_limit():
    clock = FakeClock(1000)  # 1000 正好是 window=10 的窗口起点
    c = SlidingWindowCounter(5, 10, clock=clock)
    assert c.estimated_count() == 0
    assert drain(c) == 5
    assert c.estimated_count() == 5


def test_counter_weighted_previous_window():
    clock = FakeClock(1000)
    c = SlidingWindowCounter(10, 10, clock=clock)
    assert drain(c) == 10  # 窗口 [1000, 1010) 用满
    clock.set(1012.5)  # 新窗口过去 25%，上一窗口权重 0.75
    assert c.estimated_count() == 7.5
    assert drain(c) == 2  # 7.5 + 1 <= 10，7.5 + 2 <= 10，7.5 + 3 > 10
    assert c.estimated_count() == 9.5
    clock.set(1015)  # 权重 0.5 → 5 + 2 = 7
    assert c.estimated_count() == 7
    assert drain(c) == 3


def test_counter_skipped_window_resets():
    """中间空了一整个窗口以上，上一窗口计数应当视为 0。"""
    clock = FakeClock(1000)
    c = SlidingWindowCounter(10, 10, clock=clock)
    drain(c)
    clock.set(1025)  # 跳过了 [1010, 1020)
    assert c.estimated_count() == 0
    assert drain(c) == 10


def test_counter_window_alignment():
    """窗口按 window 的整数倍对齐，而不是从第一次请求开始算。"""
    clock = FakeClock(1005)
    c = SlidingWindowCounter(4, 10, clock=clock)
    assert drain(c) == 4  # 都记在窗口 [1000, 1010)
    clock.set(1010)  # 新窗口刚开始，上一窗口权重 1
    assert c.estimated_count() == 4
    assert c.allow() is False
    clock.set(1015)  # 权重 0.5
    assert c.estimated_count() == 2
    assert drain(c) == 2


def test_counter_smooths_boundary_burst():
    clock = FakeClock(1000)
    c = SlidingWindowCounter(10, 10, clock=clock)
    clock.set(1009)
    assert drain(c) == 10
    clock.set(1011)  # 新窗口过去 10%，上一窗口权重 0.9 → 9
    assert drain(c) == 1


def test_counter_rejected_not_counted():
    clock = FakeClock(1000)
    c = SlidingWindowCounter(3, 10, clock=clock)
    drain(c)
    for _ in range(100):
        assert c.allow() is False
    assert c.estimated_count() == 3


def test_counter_constant_memory():
    clock = FakeClock(1000)
    c = SlidingWindowCounter(1000, 1, clock=clock)
    for _ in range(100_000):
        c.allow()
        clock.advance(0.0003)
    for v in vars(c).values():
        if hasattr(v, "__len__") and not isinstance(v, str):
            assert len(v) <= 2, "计数法应该是 O(1) 空间，不需要存每个请求的时间戳"


# =====================================================================
# 三种算法放一起对照
# =====================================================================


def test_all_limiters_respect_rate_under_flood():
    """每秒 100 个请求连打 60 秒，限额是每 10 秒 20 个（令牌桶：容量 20，每秒 2 个）。"""
    clock = FakeClock(1000)
    bucket = TokenBucket(20, 2, clock=clock)
    log = SlidingWindowLog(20, 10, clock=clock)
    counter = SlidingWindowCounter(20, 10, clock=clock)
    passed = {"bucket": 0, "log": 0, "counter": 0}
    for i in range(60 * 100):
        clock.set(1000 + i / 100)
        passed["bucket"] += bucket.allow()
        passed["log"] += log.allow()
        passed["counter"] += counter.allow()
    # 理论值：令牌桶 20 + 2 × 60 = 140；窗口法 60 / 10 × 20 = 120
    assert 135 <= passed["bucket"] <= 140
    assert passed["log"] == 120
    assert 110 <= passed["counter"] <= 130
