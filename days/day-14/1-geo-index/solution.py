"""Day 14 · Geohash + 四叉树（地理位置索引）。

题目见同目录 README.md。只填实现，不要改公开函数和方法的签名。
经纬度顺序一律是 (lat, lon)；边界一律是 (min_lat, min_lon, max_lat, max_lon)。
"""

from __future__ import annotations

import bisect  # noqa: F401  提示：GeoIndex 用排好序的列表 + 前缀范围扫描
import math  # noqa: F401
from typing import Dict, Hashable, List, Optional, Tuple

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
EARTH_RADIUS_KM = 6371.0

BBox = Tuple[float, float, float, float]


def geohash_encode(lat: float, lon: float, precision: int = 12) -> str:
    """从经度开始，经度纬度交替二分，每 5 比特一个 base32 字符。"""
    raise NotImplementedError


def geohash_bbox(h: str) -> BBox:
    raise NotImplementedError


def geohash_decode(h: str) -> Tuple[float, float, float, float]:
    """返回 (中心纬度, 中心经度, 半高, 半宽)。"""
    raise NotImplementedError


def geohash_neighbors(h: str) -> Dict[str, Optional[str]]:
    """8 个方向的邻居；经度绕回，越过极点的方向为 None。"""
    raise NotImplementedError


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    raise NotImplementedError


class GeoIndex:
    STORE_PRECISION = 9

    def __init__(self) -> None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def add(self, item_id: Hashable, lat: float, lon: float) -> None:
        raise NotImplementedError

    def remove(self, item_id: Hashable) -> bool:
        raise NotImplementedError

    def nearby(
        self, lat: float, lon: float, radius_km: float, limit: int = 10
    ) -> List[Tuple[Hashable, float]]:
        """查 3×3 个格子（格子不小于半径），再用 haversine 精确过滤。"""
        raise NotImplementedError


class QuadTree:
    MAX_DEPTH = 20

    def __init__(self, capacity: int = 8, bounds: BBox = (-90.0, -180.0, 90.0, 180.0)) -> None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def insert(self, item_id: Hashable, lat: float, lon: float) -> None:
        raise NotImplementedError

    def query_rect(self, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> List[Hashable]:
        """矩形内（含边界）所有点的 id，排好序。"""
        raise NotImplementedError

    def leaves(self) -> List[Tuple[BBox, int, int]]:
        """[(bounds, 点数, 深度), ...]，根节点深度为 0。"""
        raise NotImplementedError

    def depth(self) -> int:
        raise NotImplementedError
