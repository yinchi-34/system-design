import importlib.util
import random
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day19_tsdb_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
Agg = _mod.Agg
downsample = _mod.downsample
counter_increase = _mod.counter_increase
counter_rate = _mod.counter_rate
TimeSeriesDB = _mod.TimeSeriesDB
AlertRule = _mod.AlertRule


class FakeClock:
    def __init__(self, t=0):
        self.t = t

    def __call__(self):
        return self.t


# =====================================================================
# 降采样
# =====================================================================


def test_agg_basics():
    a = Agg.of(5)
    assert a == Agg(1, 5, 5, 5)
    m = a.merge(Agg.of(1)).merge(Agg.of(9))
    assert m == Agg(3, 15, 1, 9)
    assert m.value("avg") == 5 and m.value("sum") == 15
    assert m.value("min") == 1 and m.value("max") == 9 and m.value("count") == 3


def test_downsample_avg_aligned():
    pts = [(0, 1), (5, 3), (10, 10), (19, 20), (31, 7)]
    assert downsample(pts, 10) == [(0, 2.0), (10, 15.0), (30, 7.0)]


@pytest.mark.parametrize("agg,expect", [
    ("sum", [(0, 4), (10, 30)]),
    ("min", [(0, 1), (10, 10)]),
    ("max", [(0, 3), (10, 20)]),
    ("count", [(0, 2), (10, 2)]),
])
def test_downsample_other_aggs(agg, expect):
    assert downsample([(0, 1), (5, 3), (10, 10), (19, 20)], 10, agg) == expect


def test_downsample_unsorted_and_empty():
    assert downsample([(25, 1), (3, 2), (21, 3)], 10, "sum") == [(0, 2), (20, 4)]
    assert downsample([], 10) == []


def test_downsample_invalid():
    with pytest.raises(ValueError):
        downsample([(0, 1)], 0)
    with pytest.raises(ValueError):
        downsample([(0, 1)], 10, "p99")


def test_downsample_is_composable_for_mergeable_aggs():
    rng = random.Random(1)
    pts = [(t, rng.randint(0, 100)) for t in range(0, 3600, 7)]
    for agg in ("sum", "min", "max", "count"):
        two_step = downsample(downsample(pts, 60, agg), 600, {"count": "sum"}.get(agg, agg))
        assert two_step == downsample(pts, 600, agg)


def test_downsample_avg_of_avg_is_wrong():
    """为什么要存 Agg 而不是只存平均值：两个桶点数不同时，平均值的平均值不对。"""
    pts = [(0, 0), (1, 0), (2, 0), (10, 30)]
    avg_of_avg = sum(v for _, v in downsample(pts, 10)) / 2
    assert avg_of_avg == 15
    assert downsample(pts, 20) == [(0, 7.5)]


# =====================================================================
# 计数器速率
# =====================================================================


def test_counter_increase_simple():
    assert counter_increase([(0, 100), (10, 150), (20, 230)]) == 130
    assert counter_rate([(0, 100), (10, 150), (20, 230)]) == 6.5


def test_counter_handles_reset():
    # 进程在 20 和 30 之间重启了，计数器从 0 重新开始
    pts = [(0, 100), (10, 150), (20, 200), (30, 20), (40, 50)]
    assert counter_increase(pts) == 50 + 50 + 20 + 30
    assert counter_rate(pts) == 150 / 40


def test_counter_unsorted_input():
    assert counter_increase([(20, 230), (0, 100), (10, 150)]) == 130


def test_counter_too_few_points():
    assert counter_increase([]) is None
    assert counter_increase([(0, 5)]) is None
    assert counter_rate([(0, 5)]) is None


# =====================================================================
# 分级存储
# =====================================================================


def make(t=10_000, **kw):
    clock = FakeClock(t)
    args = dict(raw_retention=600, rollup_step=60, rollup_retention=3600, clock=clock)
    args.update(kw)
    return TimeSeriesDB(**args), clock


@pytest.mark.parametrize("kw", [
    dict(raw_retention=0), dict(rollup_step=0), dict(rollup_retention=600),
])
def test_db_invalid_args(kw):
    with pytest.raises(ValueError):
        make(**kw)


def test_db_add_and_raw_points():
    db, clock = make()
    db.add("cpu", 9_500, 0.5)
    db.add("cpu", 9_400, 0.2)
    db.add("cpu", 9_500, 0.7)  # 同一时间戳覆盖
    assert db.raw_points("cpu", 0, 20_000) == [(9_400, 0.2), (9_500, 0.7)]
    assert db.raw_points("cpu", 9_400, 9_500) == [(9_400, 0.2)]
    assert db.raw_count() == 2
    assert db.series() == ["cpu"]


def test_db_add_validation():
    db, clock = make()
    with pytest.raises(TypeError):
        db.add("cpu", 9_500, "1")
    with pytest.raises(TypeError):
        db.add("cpu", 9_500, True)
    with pytest.raises(TypeError):
        db.add("cpu", 9_500.5, 1)
    with pytest.raises(ValueError):
        db.add("cpu", 10_000 - 601, 1)  # 比原始数据保留期还老
    db.add("cpu", 10_000 - 600, 1)


def test_db_query_raw():
    db, clock = make()
    for t in range(9_600, 9_720, 10):
        db.add("cpu", t, t % 100)
    assert db.query("cpu", 9_600, 9_720, 60, "max") == [(9_600, 50), (9_660, 90)]
    assert db.query("cpu", 9_600, 9_660, 60, "count") == [(9_600, 6)]
    assert db.query("nope", 0, 20_000, 60) == []


def test_db_query_invalid():
    db, clock = make()
    with pytest.raises(ValueError):
        db.query("cpu", 0, 1, 90)  # 不是 rollup_step 的整数倍
    with pytest.raises(ValueError):
        db.query("cpu", 0, 1, 60, "median")


def test_db_compact_folds_old_points():
    db, clock = make()
    for t in range(9_400, 10_000, 10):
        db.add("cpu", t, 1)
    clock.t = 10_100  # 截止线 9_500
    assert db.compact() == 10
    assert db.raw_count() == 50
    assert db.rollup_count() == 3  # 9_360、9_420、9_480 三个桶
    assert db.raw_points("cpu", 0, 9_500) == []


def test_db_query_same_before_and_after_compact():
    rng = random.Random(3)
    db, clock = make(t=5_000, raw_retention=600, rollup_retention=10_000)
    pts = [(t, rng.randint(0, 50)) for t in range(4_400, 5_000, 3)]
    for t, v in pts:
        db.add("m", t, v)
    before = {agg: db.query("m", 4_000, 6_000, 120, agg) for agg in ("avg", "sum", "min", "max", "count")}
    clock.t = 5_300
    assert db.compact() > 0
    for agg, expect in before.items():
        got = db.query("m", 4_000, 6_000, 120, agg)
        assert [k for k, _ in got] == [k for k, _ in expect]
        for (_, a), (_, b) in zip(got, expect):
            assert a == pytest.approx(b)


def test_db_partial_bucket_compaction_merges():
    db, clock = make()
    db.add("m", 9_420, 1)
    db.add("m", 9_450, 5)
    clock.t = 10_040  # 截止线 9_440：只折叠 9_420
    db.compact()
    assert db.rollup_count() == 1 and db.raw_count() == 1
    clock.t = 10_100
    db.compact()
    assert db.rollup_count() == 1 and db.raw_count() == 0
    assert db.query("m", 0, 20_000, 60, "sum") == [(9_420, 6)]
    assert db.query("m", 0, 20_000, 60, "avg") == [(9_420, 3)]


def test_db_rollup_retention():
    db, clock = make()
    db.add("m", 9_420, 1)  # 桶 [9_420, 9_480)
    clock.t = 10_100
    db.compact()
    clock.t = 9_480 + 3600 - 1
    db.compact()
    assert db.rollup_count() == 1
    clock.t = 9_480 + 3600
    db.compact()
    assert db.rollup_count() == 0
    assert db.series() == []


def test_db_series_are_independent():
    db, clock = make()
    db.add("a", 9_500, 1)
    db.add("b", 9_500, 2)
    assert db.series() == ["a", "b"]
    assert db.query("a", 0, 20_000, 60, "sum") == [(9_480, 1)]


def test_db_memory_shrinks():
    db, clock = make(t=0, raw_retention=600, rollup_retention=100_000)
    for t in range(0, 3600):
        clock.t = t
        db.add("m", t, 1)
    clock.t = 3600
    db.compact()
    assert db.raw_count() == 600
    assert db.rollup_count() == 50


# =====================================================================
# 告警规则
# =====================================================================


def test_alert_invalid():
    with pytest.raises(ValueError):
        AlertRule("x", "==", 1)
    with pytest.raises(ValueError):
        AlertRule("x", ">", 1, for_seconds=-1)


def test_alert_fires_immediately_without_for():
    r = AlertRule("cpu", ">", 0.9)
    assert r.evaluate(0, 0.5) == "inactive"
    assert r.evaluate(10, 0.95) == "firing"
    assert r.events == [("firing", 10)]


def test_alert_pending_then_firing():
    r = AlertRule("cpu", ">", 0.9, for_seconds=60)
    assert r.evaluate(0, 0.95) == "pending"
    assert r.since == 0
    assert r.evaluate(30, 0.99) == "pending"
    assert r.evaluate(60, 0.91) == "firing"
    assert r.evaluate(90, 0.99) == "firing"
    assert r.events == [("firing", 60)], "持续触发不重复发告警"


def test_alert_blip_does_not_fire():
    r = AlertRule("cpu", ">", 0.9, for_seconds=60)
    r.evaluate(0, 0.95)
    r.evaluate(30, 0.5)  # 抖了一下，回到正常
    assert r.state == "inactive" and r.since is None
    r.evaluate(40, 0.95)
    assert r.evaluate(90, 0.95) == "pending", "要从 40 重新计时"
    assert r.evaluate(100, 0.95) == "firing"


def test_alert_resolves():
    r = AlertRule("err", ">=", 5)
    r.evaluate(0, 5)
    assert r.evaluate(10, 4) == "inactive"
    assert r.events == [("firing", 0), ("resolved", 10)]
    r.evaluate(20, 1)
    assert r.events == [("firing", 0), ("resolved", 10)]


def test_alert_pending_to_inactive_no_event():
    r = AlertRule("x", ">", 1, for_seconds=100)
    r.evaluate(0, 2)
    r.evaluate(10, 0)
    assert r.events == []


def test_alert_no_data_counts_as_false():
    r = AlertRule("lat", "<", 10)
    r.evaluate(0, 5)
    assert r.evaluate(10, None) == "inactive"
    assert r.events[-1] == ("resolved", 10)


@pytest.mark.parametrize("op,v,expect", [(">", 1, False), (">=", 1, True), ("<", 1, False), ("<=", 1, True)])
def test_alert_ops(op, v, expect):
    r = AlertRule("x", op, 1)
    assert (r.evaluate(0, v) == "firing") is expect


def test_alert_time_must_not_go_back():
    r = AlertRule("x", ">", 1)
    r.evaluate(10, 0)
    r.evaluate(10, 0)
    with pytest.raises(ValueError):
        r.evaluate(9, 0)
