import importlib.util
import random
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day11_cb_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
compute_backoff = _mod.compute_backoff
RetryBudget = _mod.RetryBudget
retry = _mod.retry
CircuitBreaker = _mod.CircuitBreaker
CircuitOpenError = _mod.CircuitOpenError
CLOSED, OPEN, HALF_OPEN = _mod.CLOSED, _mod.OPEN, _mod.HALF_OPEN


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class Flaky:
    """前 fail_times 次抛 exc，之后返回 result。"""

    def __init__(self, fail_times, exc=TimeoutError, result="ok"):
        self.fail_times, self.exc, self.result, self.calls = fail_times, exc, result, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc(f"fail #{self.calls}")
        return self.result


def boom():
    raise ConnectionError("down")


# =====================================================================
# 退避
# =====================================================================


@pytest.mark.parametrize("attempt, expected", [(1, 0.1), (2, 0.2), (3, 0.4), (5, 1.6), (6, 2.0), (30, 2.0)])
def test_backoff_no_jitter(attempt, expected):
    assert compute_backoff(attempt, base=0.1, cap=2.0, jitter="none") == pytest.approx(expected)


def test_backoff_full_jitter_matches_seeded_rng():
    a, b = random.Random(42), random.Random(42)
    for attempt in range(1, 10):
        exp = min(5.0, 0.5 * 2 ** (attempt - 1))
        assert compute_backoff(attempt, base=0.5, cap=5.0, jitter="full", rng=a) == b.uniform(0, exp)


def test_backoff_equal_jitter_matches_seeded_rng():
    a, b = random.Random(7), random.Random(7)
    for attempt in range(1, 10):
        exp = min(5.0, 0.5 * 2 ** (attempt - 1))
        assert compute_backoff(attempt, base=0.5, cap=5.0, jitter="equal", rng=a) == exp / 2 + b.uniform(0, exp / 2)


def test_backoff_jitter_ranges():
    rng = random.Random(1)
    full = [compute_backoff(4, base=1, cap=100, jitter="full", rng=rng) for _ in range(2000)]
    equal = [compute_backoff(4, base=1, cap=100, jitter="equal", rng=rng) for _ in range(2000)]
    assert 0 <= min(full) and max(full) <= 8
    assert 4 <= min(equal) and max(equal) <= 8
    assert len(set(round(x, 6) for x in full)) > 1000, "抖动要真的随机"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(attempt=0, base=1, cap=2),
        dict(attempt=1, base=0, cap=2),
        dict(attempt=1, base=3, cap=2),
        dict(attempt=1, base=1, cap=2, jitter="weird"),
    ],
)
def test_backoff_invalid(kwargs):
    with pytest.raises(ValueError):
        compute_backoff(kwargs.pop("attempt"), **kwargs)


# =====================================================================
# 重试预算
# =====================================================================


def test_budget_min_retries_when_idle():
    clock = FakeClock()
    b = RetryBudget(ratio=0.1, min_retries=3, window=10, clock=clock)
    assert [b.try_acquire_retry() for _ in range(4)] == [True, True, True, False]


def test_budget_ratio_of_requests():
    clock = FakeClock()
    b = RetryBudget(ratio=0.2, min_retries=0, window=10, clock=clock)
    for _ in range(50):
        b.record_request()
    granted = sum(b.try_acquire_retry() for _ in range(100))
    assert granted == 10


def test_budget_window_slides():
    clock = FakeClock()
    b = RetryBudget(ratio=0.0, min_retries=2, window=10, clock=clock)
    assert b.try_acquire_retry() and b.try_acquire_retry()
    assert not b.try_acquire_retry()
    clock.advance(9.99)
    assert not b.try_acquire_retry()
    clock.advance(0.01)  # 10 秒前的重试已经滑出窗口
    assert b.try_acquire_retry()


def test_budget_old_requests_expire():
    clock = FakeClock()
    b = RetryBudget(ratio=0.5, min_retries=0, window=5, clock=clock)
    for _ in range(10):
        b.record_request()
    clock.advance(5)
    assert b.try_acquire_retry() is False


@pytest.mark.parametrize("kwargs", [{"ratio": -0.1}, {"min_retries": -1}, {"window": 0}])
def test_budget_invalid(kwargs):
    with pytest.raises(ValueError):
        RetryBudget(**kwargs)


# =====================================================================
# retry
# =====================================================================


def test_retry_succeeds_after_failures():
    sleeps = []
    f = Flaky(2)
    assert retry(f, max_attempts=3, base=1, cap=10, jitter="none", sleep=sleeps.append) == "ok"
    assert f.calls == 3
    assert sleeps == [1, 2]


def test_retry_gives_up_and_raises_last_error():
    sleeps = []
    f = Flaky(10)
    with pytest.raises(TimeoutError, match="fail #4"):
        retry(f, max_attempts=4, base=1, cap=3, jitter="none", sleep=sleeps.append)
    assert f.calls == 4
    assert sleeps == [1, 2, 3]


def test_retry_no_sleep_on_first_success():
    sleeps = []
    assert retry(lambda: 42, sleep=sleeps.append) == 42
    assert sleeps == []


def test_retry_non_retryable_raises_immediately():
    sleeps = []
    f = Flaky(5, exc=ValueError)
    with pytest.raises(ValueError):
        retry(f, retry_on=(TimeoutError,), sleep=sleeps.append)
    assert f.calls == 1 and sleeps == []


def test_retry_uses_jitter_with_rng():
    sleeps = []
    rng, ref = random.Random(5), random.Random(5)
    retry(Flaky(2), max_attempts=3, base=1, cap=10, jitter="full", rng=rng, sleep=sleeps.append)
    assert sleeps == [ref.uniform(0, 1), ref.uniform(0, 2)]


def test_retry_honors_retry_after():
    class RateLimited(Exception):
        def __init__(self, retry_after):
            super().__init__("429")
            self.retry_after = retry_after

    calls = []

    def f():
        calls.append(1)
        if len(calls) == 1:
            raise RateLimited(7.5)
        if len(calls) == 2:
            raise RateLimited(0.01)
        return "done"

    sleeps = []
    assert retry(f, max_attempts=5, base=1, cap=10, jitter="none", sleep=sleeps.append) == "done"
    assert sleeps == [7.5, 2], "retry_after 和退避时间取较大值"


def test_retry_respects_budget():
    clock = FakeClock()
    budget = RetryBudget(ratio=0.0, min_retries=1, window=60, clock=clock)
    sleeps = []
    f1 = Flaky(1)
    assert retry(f1, budget=budget, jitter="none", sleep=sleeps.append) == "ok"
    f2 = Flaky(1)
    with pytest.raises(TimeoutError):
        retry(f2, budget=budget, jitter="none", sleep=sleeps.append)
    assert f2.calls == 1, "预算用完了就不能再重试"


def test_retry_records_one_request_per_call():
    clock = FakeClock()
    budget = RetryBudget(ratio=0.5, min_retries=0, window=60, clock=clock)
    for _ in range(4):
        retry(lambda: 1, budget=budget)
    # 4 次请求 × 0.5 = 2 次重试额度
    assert sum(budget.try_acquire_retry() for _ in range(5)) == 2


def test_retry_invalid_attempts():
    with pytest.raises(ValueError):
        retry(lambda: 1, max_attempts=0)


# =====================================================================
# 熔断器
# =====================================================================


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def transitions():
    return []


@pytest.fixture
def cb(clock, transitions):
    return CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=10,
        failure_exceptions=(ConnectionError, TimeoutError),
        clock=clock,
        on_state_change=lambda old, new: transitions.append((old, new)),
    )


def trip(cb, n=3):
    for _ in range(n):
        with pytest.raises(ConnectionError):
            cb.call(boom)


def test_breaker_passes_through_results_and_args(cb):
    assert cb.call(lambda a, b=0: a + b, 2, b=3) == 5
    assert cb.state == CLOSED


def test_breaker_opens_after_consecutive_failures(cb, transitions):
    trip(cb, 2)
    assert cb.state == CLOSED and cb.failure_count == 2
    trip(cb, 1)
    assert cb.state == OPEN
    assert transitions == [(CLOSED, OPEN)]


def test_breaker_success_resets_count(cb):
    trip(cb, 2)
    cb.call(lambda: None)
    assert cb.failure_count == 0
    trip(cb, 2)
    assert cb.state == CLOSED


def test_breaker_open_rejects_without_calling(cb, clock):
    trip(cb)
    called = []
    clock.advance(4)
    with pytest.raises(CircuitOpenError) as ei:
        cb.call(lambda: called.append(1))
    assert called == []
    assert ei.value.retry_after == pytest.approx(6)


def test_breaker_half_open_after_timeout(cb, clock, transitions):
    trip(cb)
    clock.advance(9.99)
    assert cb.state == OPEN
    clock.advance(0.01)
    assert cb.state == HALF_OPEN
    assert transitions == [(CLOSED, OPEN), (OPEN, HALF_OPEN)]


def test_breaker_half_open_success_closes(cb, clock, transitions):
    trip(cb)
    clock.advance(10)
    assert cb.call(lambda: "probe") == "probe"
    assert cb.state == CLOSED
    assert cb.failure_count == 0
    assert transitions[-1] == (HALF_OPEN, CLOSED)


def test_breaker_half_open_failure_reopens_and_restarts_timer(cb, clock):
    trip(cb)
    clock.advance(10)
    with pytest.raises(ConnectionError):
        cb.call(boom)
    assert cb.state == OPEN
    clock.advance(9)
    assert cb.state == OPEN, "重新打开后要重新计时"
    clock.advance(1)
    assert cb.state == HALF_OPEN


def test_breaker_half_open_limits_concurrent_probes(cb, clock):
    trip(cb)
    clock.advance(10)
    inner = []

    def probe():
        # 试探调用还在进行中，此时另一个请求进来
        with pytest.raises(CircuitOpenError):
            cb.call(lambda: inner.append("should not run"))
        return "probe ok"

    assert cb.call(probe) == "probe ok", "持锁调用 func 会在这里死锁"
    assert inner == []
    assert cb.state == CLOSED


def test_breaker_half_open_needs_all_probes(clock):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=5, half_open_max_calls=3, clock=clock)
    with pytest.raises(ConnectionError):
        cb.call(boom)
    clock.advance(5)
    cb.call(lambda: 1)
    cb.call(lambda: 2)
    assert cb.state == HALF_OPEN
    cb.call(lambda: 3)
    assert cb.state == CLOSED


def test_breaker_half_open_extra_calls_rejected(clock):
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=5, half_open_max_calls=2, clock=clock)
    with pytest.raises(ConnectionError):
        cb.call(boom)
    clock.advance(5)
    results = []

    def slow_probe():
        results.append(cb.call(lambda: "second probe"))   # 第 2 个名额
        with pytest.raises(CircuitOpenError) as ei:
            cb.call(lambda: "third")                       # 名额用完
        assert ei.value.retry_after == 0
        return "first probe"

    assert cb.call(slow_probe) == "first probe"
    assert results == ["second probe"]
    assert cb.state == CLOSED


def test_breaker_non_failure_exceptions_count_as_success(cb):
    trip(cb, 2)
    with pytest.raises(KeyError):
        cb.call(lambda: {}["missing"])  # 业务错误，下游是健康的
    assert cb.failure_count == 0
    assert cb.state == CLOSED


def test_breaker_non_failure_exception_in_half_open_closes(cb, clock):
    trip(cb)
    clock.advance(10)
    with pytest.raises(KeyError):
        cb.call(lambda: {}["missing"])
    assert cb.state == CLOSED


def test_breaker_reset(cb, transitions):
    trip(cb)
    cb.reset()
    assert cb.state == CLOSED
    assert cb.failure_count == 0
    assert transitions[-1] == (OPEN, CLOSED)
    cb.reset()
    assert transitions.count((OPEN, CLOSED)) == 1, "状态没变化时不回调"


@pytest.mark.parametrize(
    "kwargs", [{"failure_threshold": 0}, {"recovery_timeout": 0}, {"half_open_max_calls": 0}]
)
def test_breaker_invalid(kwargs):
    with pytest.raises(ValueError):
        CircuitBreaker(**kwargs)


def test_breaker_with_retry_waits_for_half_open(cb, clock):
    trip(cb)
    sleeps = []

    def sleep(d):
        sleeps.append(d)
        clock.advance(d)

    result = retry(
        lambda: cb.call(lambda: "recovered"),
        max_attempts=3,
        base=0.1,
        cap=1,
        jitter="none",
        retry_on=(CircuitOpenError,),
        sleep=sleep,
    )
    assert result == "recovered"
    assert sleeps == [pytest.approx(10)], "用 CircuitOpenError.retry_after 决定等多久"
