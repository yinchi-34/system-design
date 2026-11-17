import importlib.util
import math
import random
import sys
import time
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day14_geo_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
geohash_encode = _mod.geohash_encode
geohash_decode = _mod.geohash_decode
geohash_bbox = _mod.geohash_bbox
geohash_neighbors = _mod.geohash_neighbors
haversine_km = _mod.haversine_km
GeoIndex = _mod.GeoIndex
QuadTree = _mod.QuadTree


def brute_nearby(points, lat, lon, r, limit):
    res = []
    for iid, (la, lo) in points.items():
        d = haversine_km(lat, lon, la, lo)
        if d <= r:
            res.append((d, iid))
    res.sort()
    return [iid for _, iid in res[:limit]]


def random_points(n, rnd, lat_range=(39.7, 40.1), lon_range=(116.2, 116.6)):
    return {f"p{i}": (rnd.uniform(*lat_range), rnd.uniform(*lon_range)) for i in range(n)}


# =====================================================================
# Geohash
# =====================================================================


@pytest.mark.parametrize(
    "lat, lon, p, expected",
    [
        (57.64911, 10.40744, 11, "u4pruydqqvj"),
        (39.9087, 116.3975, 7, "wx4g09n"),
        (0.0, 0.0, 5, "s0000"),
        (-90.0, -180.0, 4, "0000"),
        (90.0, 180.0, 4, "zzzz"),
        (37.7749, -122.4194, 6, "9q8yyk"),
    ],
)
def test_geohash_encode_known(lat, lon, p, expected):
    assert geohash_encode(lat, lon, p) == expected


def test_geohash_default_precision_and_prefix_property():
    h12 = geohash_encode(31.2304, 121.4737)
    assert len(h12) == 12
    for p in range(1, 12):
        assert geohash_encode(31.2304, 121.4737, p) == h12[:p]


@pytest.mark.parametrize("args", [(91, 0, 5), (0, 181, 5), (-90.1, 0, 5), (0, 0, 0), (0, 0, 13)])
def test_geohash_encode_invalid(args):
    with pytest.raises(ValueError):
        geohash_encode(*args)


def test_geohash_bbox_and_decode():
    a, b, c, d = geohash_bbox("u4pruyd")
    assert a <= 57.64911 <= c and b <= 10.40744 <= d
    lat, lon, dlat, dlon = geohash_decode("u4pruyd")
    assert lat == pytest.approx((a + c) / 2) and lon == pytest.approx((b + d) / 2)
    assert dlat == pytest.approx((c - a) / 2) and dlon == pytest.approx((d - b) / 2)
    assert geohash_bbox("s") == (0.0, 0.0, 45.0, 45.0)


def test_geohash_roundtrip_random():
    rnd = random.Random(14)
    for _ in range(2000):
        lat, lon = rnd.uniform(-90, 90), rnd.uniform(-180, 180)
        p = rnd.randint(1, 12)
        h = geohash_encode(lat, lon, p)
        a, b, c, d = geohash_bbox(h)
        assert a <= lat <= c and b <= lon <= d
        assert geohash_encode((a + c) / 2, (b + d) / 2, p) == h


@pytest.mark.parametrize("bad", ["", "u4a", "U4P", "hello!"])
def test_geohash_bbox_invalid(bad):
    with pytest.raises(ValueError):
        geohash_bbox(bad)


def test_geohash_neighbors_known():
    assert geohash_neighbors("u4pruyd") == {
        "n": "u4pruyf", "ne": "u4pruyg", "e": "u4pruye", "se": "u4pruy7",
        "s": "u4pruy6", "sw": "u4pruy3", "w": "u4pruy9", "nw": "u4pruyc",
    }


def test_geohash_neighbors_are_adjacent():
    h = geohash_encode(22.3193, 114.1694, 6)
    a, b, c, d = geohash_bbox(h)
    nb = geohash_neighbors(h)
    na, nb_, nc, nd = geohash_bbox(nb["n"])
    assert na == pytest.approx(c) and nb_ == pytest.approx(b)
    ea, eb, ec, ed = geohash_bbox(nb["e"])
    assert eb == pytest.approx(d) and ea == pytest.approx(a)
    assert len(set(nb.values()) | {h}) == 9


def test_geohash_neighbors_wrap_longitude():
    h = geohash_encode(0.5, 179.99, 5)
    east = geohash_neighbors(h)["e"]
    a, b, c, d = geohash_bbox(east)
    assert b == pytest.approx(-180.0), "日期变更线另一侧是邻居"


def test_geohash_neighbors_pole_is_none():
    h = geohash_encode(89.99, 10, 3)
    nb = geohash_neighbors(h)
    assert nb["n"] is None and nb["ne"] is None and nb["nw"] is None
    assert nb["s"] is not None


def test_haversine():
    assert haversine_km(0, 0, 0, 0) == 0
    # 北京天安门 → 上海人民广场约 1067 km
    assert haversine_km(39.9087, 116.3975, 31.2304, 121.4737) == pytest.approx(1067, rel=0.01)
    # 赤道上经度 1 度
    assert haversine_km(0, 0, 0, 1) == pytest.approx(2 * math.pi * 6371 / 360, rel=1e-6)
    assert haversine_km(0, 179.5, 0, -179.5) == pytest.approx(111.19, rel=0.01)


# =====================================================================
# GeoIndex
# =====================================================================


def test_index_basic():
    idx = GeoIndex()
    idx.add("cafe-1", 39.9087, 116.3975)
    idx.add("cafe-2", 39.9200, 116.4000)
    idx.add("far", 31.2304, 121.4737)
    assert len(idx) == 3
    res = idx.nearby(39.91, 116.40, radius_km=1)
    assert [r[0] for r in res] == ["cafe-1"]
    assert res[0][1] == pytest.approx(haversine_km(39.91, 116.40, 39.9087, 116.3975))
    assert [r[0] for r in idx.nearby(39.91, 116.40, radius_km=2)] == ["cafe-1", "cafe-2"]


def test_index_update_and_remove():
    idx = GeoIndex()
    idx.add("shop", 39.90, 116.40)
    idx.add("shop", 31.23, 121.47)  # 搬家
    assert len(idx) == 1
    assert idx.nearby(39.90, 116.40, 5) == []
    assert [r[0] for r in idx.nearby(31.23, 121.47, 5)] == ["shop"]
    assert idx.remove("shop") is True
    assert idx.remove("shop") is False
    assert idx.nearby(31.23, 121.47, 5) == []


def test_index_limit_and_ties():
    idx = GeoIndex()
    for name in ["c", "a", "b"]:
        idx.add(name, 10.0, 10.0)
    idx.add("near", 10.001, 10.0)
    res = idx.nearby(10.0, 10.0, 1, limit=3)
    assert [r[0] for r in res] == ["a", "b", "c"]


def test_index_invalid():
    idx = GeoIndex()
    with pytest.raises(ValueError):
        idx.add("x", 100, 0)
    with pytest.raises(ValueError):
        idx.nearby(0, 0, 0)
    with pytest.raises(ValueError):
        idx.nearby(0, 0, 1, limit=0)


@pytest.mark.parametrize("radius", [0.05, 0.3, 1.0, 3.0, 10.0])
def test_index_matches_brute_force(radius):
    rnd = random.Random(int(radius * 100))
    pts = random_points(5000, rnd)
    idx = GeoIndex()
    for iid, (la, lo) in pts.items():
        idx.add(iid, la, lo)
    for _ in range(30):
        lat, lon = rnd.uniform(39.7, 40.1), rnd.uniform(116.2, 116.6)
        got = [r[0] for r in idx.nearby(lat, lon, radius, limit=50)]
        assert got == brute_nearby(pts, lat, lon, radius, 50)


def test_index_cell_boundary():
    # 赤道和本初子午线交汇处：四个点分属完全不同的 geohash 前缀
    idx = GeoIndex()
    pts = {"ne": (0.001, 0.001), "nw": (0.001, -0.001), "se": (-0.001, 0.001), "sw": (-0.001, -0.001)}
    for iid, (la, lo) in pts.items():
        idx.add(iid, la, lo)
    assert len({geohash_encode(la, lo, 3) for la, lo in pts.values()}) == 4
    assert sorted(r[0] for r in idx.nearby(0.0005, 0.0005, 1)) == ["ne", "nw", "se", "sw"]


def test_index_across_antimeridian():
    idx = GeoIndex()
    idx.add("fiji-east", -17.0, 179.99)
    idx.add("fiji-west", -17.0, -179.99)
    res = idx.nearby(-17.0, 179.995, 5)
    assert sorted(r[0] for r in res) == ["fiji-east", "fiji-west"]


def test_index_high_latitude():
    rnd = random.Random(70)
    pts = random_points(2000, rnd, lat_range=(69.0, 71.0), lon_range=(20.0, 26.0))
    idx = GeoIndex()
    for iid, (la, lo) in pts.items():
        idx.add(iid, la, lo)
    for _ in range(20):
        lat, lon = rnd.uniform(69.2, 70.8), rnd.uniform(21, 25)
        got = [r[0] for r in idx.nearby(lat, lon, 8, limit=100)]
        assert got == brute_nearby(pts, lat, lon, 8, 100), "高纬度格子更窄，宽度估算要考虑 cos(纬度)"


def test_index_perf_no_full_scan():
    rnd = random.Random(1)
    idx = GeoIndex()
    for i in range(100_000):
        idx.add(i, rnd.uniform(18, 53), rnd.uniform(73, 135))  # 撒满全国
    start = time.perf_counter()
    for _ in range(1000):
        idx.nearby(rnd.uniform(20, 50), rnd.uniform(80, 130), 2)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"1000 次查询用了 {elapsed:.1f}s，是不是遍历了所有点？"


# =====================================================================
# 四叉树
# =====================================================================


def test_quadtree_basic():
    qt = QuadTree(capacity=4)
    qt.insert("a", 31.23, 121.47)
    qt.insert("b", 39.90, 116.40)
    assert len(qt) == 2
    assert qt.query_rect(31, 121, 32, 122) == ["a"]
    assert qt.query_rect(-90, -180, 90, 180) == ["a", "b"]
    assert qt.query_rect(0, 0, 1, 1) == []
    assert qt.depth() == 0


def test_quadtree_boundary_inclusive():
    qt = QuadTree(capacity=1)
    qt.insert("edge", 10.0, 20.0)
    qt.insert("other", -10.0, -20.0)
    assert qt.query_rect(10.0, 20.0, 11.0, 21.0) == ["edge"]
    assert qt.query_rect(9.0, 19.0, 10.0, 20.0) == ["edge"]


def test_quadtree_splits_and_respects_capacity():
    rnd = random.Random(2)
    qt = QuadTree(capacity=8)
    for i in range(3000):
        qt.insert(i, rnd.uniform(-60, 60), rnd.uniform(-170, 170))
    leaves = qt.leaves()
    assert sum(c for _, c, _ in leaves) == 3000
    assert all(c <= 8 for _, c, d in leaves if d < QuadTree.MAX_DEPTH)
    assert qt.depth() >= 5


def test_quadtree_split_rule():
    qt = QuadTree(capacity=1, bounds=(0.0, 0.0, 10.0, 10.0))
    qt.insert("mid", 5.0, 5.0)        # 正好在中线上：去东北
    qt.insert("sw", 1.0, 1.0)
    leaves = {(b, c) for b, c, _ in qt.leaves()}
    assert ((5.0, 5.0, 10.0, 10.0), 1) in leaves
    assert ((0.0, 0.0, 5.0, 5.0), 1) in leaves


def test_quadtree_adapts_to_density():
    rnd = random.Random(3)
    qt = QuadTree(capacity=10)
    for i in range(2000):  # 2000 个点挤在国贸附近 1 km 内
        qt.insert(f"cbd{i}", rnd.uniform(39.905, 39.915), rnd.uniform(116.455, 116.465))
    for i in range(20):    # 20 个点散在全球
        qt.insert(f"world{i}", rnd.uniform(-80, 80), rnd.uniform(-180, 180))
    leaves = qt.leaves()
    deep = [d for _, c, d in leaves if c > 0 and d >= 12]
    assert deep, "密集区域应该切得很细"
    assert len(leaves) < 2000, "稀疏区域不应该被切碎"


def test_quadtree_same_point_many_times():
    qt = QuadTree(capacity=2)
    for i in range(50):
        qt.insert(i, 1.0, 1.0)
    assert qt.depth() == QuadTree.MAX_DEPTH
    assert qt.query_rect(1, 1, 1, 1) == list(range(50))


def test_quadtree_matches_brute_force():
    rnd = random.Random(4)
    pts = random_points(3000, rnd)
    qt = QuadTree(capacity=16)
    for iid, (la, lo) in pts.items():
        qt.insert(iid, la, lo)
    for _ in range(100):
        a, c = sorted((rnd.uniform(39.7, 40.1), rnd.uniform(39.7, 40.1)))
        b, d = sorted((rnd.uniform(116.2, 116.6), rnd.uniform(116.2, 116.6)))
        expected = sorted(i for i, (la, lo) in pts.items() if a <= la <= c and b <= lo <= d)
        assert qt.query_rect(a, b, c, d) == expected


def test_quadtree_invalid():
    with pytest.raises(ValueError):
        QuadTree(capacity=0)
    qt = QuadTree(bounds=(0.0, 0.0, 10.0, 10.0))
    with pytest.raises(ValueError):
        qt.insert("x", 11, 5)
