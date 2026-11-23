import importlib.util
import math
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day18_cms_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
CountMinSketch = _mod.CountMinSketch
TopK = _mod.TopK
TrendingTracker = _mod.TrendingTracker
row_index = _mod.row_index


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def zipf_stream(n_items, n_events, s=1.2, seed=7):
    """少数词很热、大量词很冷的搜索流，像真实热搜。"""
    rng = random.Random(seed)
    words = [f"w{i}" for i in range(n_items)]
    weights = [1 / (i + 1) ** s for i in range(n_items)]
    return rng.choices(words, weights=weights, k=n_events)


# =====================================================================
# Count-Min Sketch
# =====================================================================


def test_cms_invalid_args():
    for w, d in [(0, 3), (3, 0), (-1, 1)]:
        with pytest.raises(ValueError):
            CountMinSketch(w, d)


def test_cms_empty():
    s = CountMinSketch(50, 4)
    assert s.estimate("x") == 0
    assert s.total == 0
    assert s.table == [[0] * 50 for _ in range(4)]


def test_cms_exact_table_layout():
    s = CountMinSketch(7, 3)
    s.add("hello", 5)
    t = s.table
    for r in range(3):
        for c in range(7):
            assert t[r][c] == (5 if c == row_index("hello", r, 7) else 0)


def test_cms_add_returns_estimate():
    s = CountMinSketch(100, 4)
    assert s.add("a") == 1
    assert s.add("a", 3) == 4
    assert s.estimate("a") == 4
    assert s.total == 4


def test_cms_str_and_bytes_same():
    s = CountMinSketch(100, 4)
    s.add("热搜", 2)
    assert s.estimate("热搜".encode("utf-8")) == 2


def test_cms_bad_items_and_counts():
    s = CountMinSketch(10, 2)
    with pytest.raises(TypeError):
        s.add(123)
    with pytest.raises(TypeError):
        s.estimate(None)
    with pytest.raises(TypeError):
        s.add("a", 1.5)
    with pytest.raises(ValueError):
        s.add("a", -1)
    s.add("a", 0)
    assert s.estimate("a") == 0


def test_cms_table_is_copy():
    s = CountMinSketch(5, 2)
    s.table[0][0] = 99
    assert s.table[0][0] == 0


def test_cms_never_underestimates():
    s = CountMinSketch(20, 3)  # 故意很小，碰撞很多
    stream = zipf_stream(500, 5000)
    for w in stream:
        s.add(w)
    for w, c in Counter(stream).items():
        assert s.estimate(w) >= c


def test_cms_error_bound():
    eps, delta = 0.01, 0.01
    s = CountMinSketch.from_error(eps, delta)
    assert s.width == math.ceil(math.e / eps) and s.depth == math.ceil(math.log(1 / delta))
    stream = zipf_stream(5000, 20000)
    for w in stream:
        s.add(w)
    truth = Counter(stream)
    over = sum(1 for w, c in truth.items() if s.estimate(w) - c > eps * len(stream))
    assert over <= 0.02 * len(truth), "超出 ε·N 的比例应该在 δ 附近"


@pytest.mark.parametrize("eps,delta", [(0, 0.1), (1, 0.1), (0.1, 0), (0.1, 1)])
def test_cms_from_error_invalid(eps, delta):
    with pytest.raises(ValueError):
        CountMinSketch.from_error(eps, delta)


def test_cms_merge():
    a, b = CountMinSketch(30, 3), CountMinSketch(30, 3)
    a.add("x", 2)
    b.add("x", 3)
    b.add("y", 1)
    m = a.merge(b)
    assert m.estimate("x") >= 5 and m.estimate("y") >= 1
    assert m.total == 6
    assert m.table == [[p + q for p, q in zip(r1, r2)] for r1, r2 in zip(a.table, b.table)]
    assert a.estimate("x") == 2 and b.estimate("x") == 3, "merge 不修改输入"
    with pytest.raises(ValueError):
        a.merge(CountMinSketch(31, 3))


def test_cms_conservative_update_exact_rule():
    s = CountMinSketch(4, 2, conservative=True)
    # 手动构造：先让 "a" 所在的格子各不相同
    s.add("a", 3)
    before = s.table
    idx = [row_index("b", r, 4) for r in range(2)]
    est_b = min(before[r][idx[r]] for r in range(2))
    s.add("b", 2)
    after = s.table
    for r in range(2):
        assert after[r][idx[r]] == max(before[r][idx[r]], est_b + 2)


def test_cms_conservative_is_tighter_but_still_safe():
    stream = zipf_stream(500, 5000)
    plain = CountMinSketch(30, 3)
    cons = CountMinSketch(30, 3, conservative=True)
    for w in stream:
        plain.add(w)
        cons.add(w)
    truth = Counter(stream)
    for w, c in truth.items():
        assert c <= cons.estimate(w) <= plain.estimate(w)
    err_plain = sum(plain.estimate(w) - c for w, c in truth.items())
    err_cons = sum(cons.estimate(w) - c for w, c in truth.items())
    assert err_cons < err_plain


# =====================================================================
# Top-K
# =====================================================================


def test_topk_invalid():
    with pytest.raises(ValueError):
        TopK(0, CountMinSketch(10, 2))


def test_topk_fills_then_competes():
    t = TopK(2, CountMinSketch(1000, 5))
    assert t.add("a") and t.add("b")
    assert t.add("c") is False, "c 的估计 1 不严格大于最小的候选"
    assert t.add("c") is True, "c 到 2 了，挤掉 a 或 b 里估计最小、字典序最小的 a"
    assert t.candidates() == {"b", "c"}


def test_topk_order_and_ties():
    t = TopK(3, CountMinSketch(1000, 5))
    for w, c in [("x", 5), ("a", 5), ("m", 9)]:
        t.add(w, c)
    assert t.top() == [("m", 9), ("a", 5), ("x", 5)]
    assert t.top(1) == [("m", 9)]


def test_topk_candidates_is_copy():
    t = TopK(2, CountMinSketch(100, 3))
    t.add("a")
    t.candidates().add("zzz")
    assert t.candidates() == {"a"}


def test_topk_finds_heavy_hitters_in_zipf_stream():
    stream = zipf_stream(10000, 50000)
    t = TopK(10, CountMinSketch.from_error(0.001, 0.01))
    for w in stream:
        t.add(w)
    true_top = [w for w, _ in Counter(stream).most_common(10)]
    got = [w for w, _ in t.top()]
    assert len(set(got) & set(true_top)) >= 9
    assert got[:3] == true_top[:3]


def test_topk_late_burst_takes_over():
    t = TopK(3, CountMinSketch(500, 4))
    for w in ["a"] * 10 + ["b"] * 8 + ["c"] * 6:
        t.add(w)
    for _ in range(20):
        t.add("new")
    assert t.top()[0] == ("new", 20)
    assert "c" not in t.candidates()


def test_topk_shares_sketch():
    s = CountMinSketch(100, 3)
    t = TopK(2, s)
    t.add("a", 4)
    assert s.estimate("a") == 4 and s.total == 4


# =====================================================================
# 滑动窗口热搜
# =====================================================================


@pytest.mark.parametrize("kw", [dict(k=0), dict(bucket=0), dict(window=0), dict(window=100, bucket=60)])
def test_trend_invalid(kw):
    args = dict(k=3, width=50, depth=3, window=300, bucket=60, clock=FakeClock())
    args.update(kw)
    k = args.pop("k")
    with pytest.raises(ValueError):
        TrendingTracker(k, args.pop("width"), args.pop("depth"), **args)


def make(clock, k=3):
    return TrendingTracker(k, 500, 4, window=300, bucket=60, clock=clock)


def test_trend_basic():
    clock = FakeClock()
    tr = make(clock)
    for w, c in [("a", 5), ("b", 3), ("c", 9), ("d", 1)]:
        tr.add(w, c)
    assert tr.trending() == [("c", 9), ("a", 5), ("b", 3)]
    assert tr.trending(2) == [("c", 9), ("a", 5)]
    assert tr.estimate("d") == 1


def test_trend_sums_across_buckets():
    clock = FakeClock()
    tr = make(clock)
    for i in range(5):
        if i:
            clock.advance(60)
        tr.add("a", 2)
    assert tr.live_buckets() == 5
    assert tr.estimate("a") == 10


def test_trend_bucket_boundaries():
    clock = FakeClock(59.9)
    tr = make(clock)
    tr.add("a")
    clock.t = 60.0
    tr.add("a")
    assert tr.live_buckets() == 2
    clock.t = 359.9  # 桶 5：桶 0 已经出窗口，桶 1 还在
    assert tr.live_buckets() == 1
    assert tr.estimate("a") == 1
    clock.t = 360.0
    assert tr.live_buckets() == 0
    assert tr.estimate("a") == 0


def test_trend_old_topic_falls_off():
    clock = FakeClock()
    tr = make(clock, k=2)
    tr.add("old", 100)
    clock.advance(120)
    tr.add("new", 10)
    tr.add("other", 5)
    assert tr.trending()[0] == ("old", 100)
    clock.advance(200)  # old 所在的桶出窗口
    assert tr.trending() == [("new", 10), ("other", 5)]


def test_trend_candidate_from_earlier_bucket():
    """x 在每个桶都只是第 2 名，但加起来是第 1。"""
    clock = FakeClock()
    tr = make(clock, k=2)
    for i in range(4):
        tr.add(f"burst{i}", 10)
        tr.add("x", 6)
        clock.advance(60)
    top = tr.trending()
    assert top[0] == ("x", 24)


def test_trend_empty():
    tr = make(FakeClock())
    assert tr.trending() == []
    assert tr.live_buckets() == 0
