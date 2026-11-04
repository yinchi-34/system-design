import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "day01_lru_solution", Path(__file__).with_name("solution.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
LRUCache = _mod.LRUCache


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


# ---------- 基本行为 ----------


def test_invalid_capacity():
    with pytest.raises(ValueError):
        LRUCache(0)
    with pytest.raises(ValueError):
        LRUCache(-1)


def test_get_missing_returns_default():
    cache = LRUCache(2)
    assert cache.get("x") is None
    assert cache.get("x", "fallback") == "fallback"


def test_put_and_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert len(cache) == 2


def test_falsy_values_are_stored():
    cache = LRUCache(3)
    cache.put("zero", 0)
    cache.put("none", None)
    cache.put("empty", "")
    assert cache.get("zero", "miss") == 0
    assert cache.get("none", "miss") is None
    assert cache.get("empty", "miss") == ""
    assert "none" in cache


def test_update_existing_key_does_not_grow():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("a", 10)
    assert cache.get("a") == 10
    assert len(cache) == 1


# ---------- LRU 淘汰 ----------


def test_evicts_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert "a" not in cache
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_get_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert "b" not in cache
    assert "a" in cache and "c" in cache


def test_put_existing_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 100)
    cache.put("c", 3)
    assert "b" not in cache
    assert cache.get("a") == 100


def test_update_when_full_does_not_evict():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("b", 20)
    assert "a" in cache and "b" in cache


def test_contains_does_not_refresh_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" in cache
    cache.put("c", 3)
    assert "a" not in cache


def test_get_miss_does_not_change_order():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("zzz")
    cache.put("c", 3)
    assert "a" not in cache


def test_capacity_one():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert "a" not in cache
    assert cache.get("b") == 2
    assert len(cache) == 1


def test_long_eviction_sequence():
    cache = LRUCache(3)
    for i in range(100):
        cache.put(i, i * i)
    assert len(cache) == 3
    for i in range(97):
        assert i not in cache
    for i in range(97, 100):
        assert cache.get(i) == i * i


# ---------- delete ----------


def test_delete():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.delete("a") is True
    assert cache.delete("a") is False
    assert "a" not in cache
    assert len(cache) == 0


def test_delete_frees_slot():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.delete("a")
    cache.put("c", 3)
    assert "b" in cache and "c" in cache
    assert len(cache) == 2


def test_delete_middle_keeps_order_intact():
    cache = LRUCache(3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    cache.delete("b")
    cache.put("d", 4)
    cache.put("e", 5)
    assert "a" not in cache
    assert "c" in cache and "d" in cache and "e" in cache


# ---------- TTL ----------


def test_invalid_ttl():
    with pytest.raises(ValueError):
        LRUCache(2, default_ttl=0)
    with pytest.raises(ValueError):
        LRUCache(2, default_ttl=-5)
    cache = LRUCache(2)
    with pytest.raises(ValueError):
        cache.put("a", 1, ttl=0)
    with pytest.raises(ValueError):
        cache.put("a", 1, ttl=-1)


def test_no_ttl_never_expires(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1)
    clock.advance(10**9)
    assert cache.get("a") == 1


def test_per_key_ttl_expires(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=5)
    clock.advance(4.999)
    assert cache.get("a") == 1
    clock.advance(0.001)  # 正好到期：clock() >= t + ttl
    assert cache.get("a") is None
    assert cache.get("a", "gone") == "gone"


def test_default_ttl_applies(clock):
    cache = LRUCache(2, default_ttl=10, clock=clock)
    cache.put("a", 1)
    clock.advance(9)
    assert "a" in cache
    clock.advance(1)
    assert "a" not in cache


def test_explicit_ttl_overrides_default(clock):
    cache = LRUCache(2, default_ttl=10, clock=clock)
    cache.put("short", 1, ttl=2)
    cache.put("long", 2, ttl=100)
    clock.advance(50)
    assert "short" not in cache
    assert "long" in cache


def test_put_resets_ttl(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=5)
    clock.advance(4)
    cache.put("a", 2, ttl=5)
    clock.advance(4)
    assert cache.get("a") == 2
    clock.advance(1)
    assert "a" not in cache


def test_put_without_ttl_on_existing_key_uses_default(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=5)
    cache.put("a", 2)  # default_ttl 为 None：不再过期
    clock.advance(100)
    assert cache.get("a") == 2


def test_get_does_not_extend_ttl(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=5)
    clock.advance(3)
    assert cache.get("a") == 1
    clock.advance(2)
    assert "a" not in cache


def test_delete_expired_returns_false(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=1)
    clock.advance(1)
    assert cache.delete("a") is False


def test_expired_key_can_be_reinserted(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=1)
    clock.advance(2)
    cache.put("a", 2, ttl=1)
    assert cache.get("a") == 2


def test_expired_entry_slot_is_reusable(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=1)
    cache.put("b", 2)
    clock.advance(1)
    assert cache.get("a") is None  # 访问触发清理
    cache.put("c", 3)
    assert "b" in cache and "c" in cache


def test_uses_injected_clock_only(clock):
    cache = LRUCache(2, clock=clock)
    cache.put("a", 1, ttl=0.5)
    # 真实时间几乎没流逝，但假时钟走了 1 秒
    clock.advance(1)
    assert "a" not in cache


# ---------- 规模（O(1) 的话应在 1 秒内跑完）----------


def test_many_operations():
    n = 200_000
    cache = LRUCache(10_000)
    for i in range(n):
        cache.put(i, i)
        if i % 3 == 0:
            cache.get(i // 2)
    assert len(cache) == 10_000
    assert cache.get(n - 1) == n - 1
    assert 0 not in cache
