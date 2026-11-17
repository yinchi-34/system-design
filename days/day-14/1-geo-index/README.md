# Day 14 · 动手题：Geohash + 四叉树（地理位置索引）

## 背景

「附近 3 公里的咖啡店」「离你最近的 5 辆车」「附近的人」。这些功能的核心问题是：**给一个点和半径，怎么快速找出附近的点？**

最笨的办法是把所有点都算一遍距离。1 亿个商家，每次查询算 1 亿次距离，显然不行。普通数据库的索引（B+ 树）只能对 **一维** 数据排序，而位置是二维的（纬度、经度）。只给纬度建索引，「纬度相近」的点可能在地球的另一边。

两种经典的解决思路，今天都实现：

1. **Geohash**：把二维的经纬度 **编码成一个字符串**，让「位置相近的点，字符串前缀也大概率相同」。这样二维查询就变成了一维的 **前缀查询**，任何支持排序的存储（B+ 树、Redis 有序集合、Cassandra）都能用。Redis 的 `GEOADD` / `GEOSEARCH` 和 Elasticsearch 的 `geohash_grid` 都基于它。
2. **四叉树**（Quadtree）：把地图递归地切成 4 块，一个格子里的点太多就继续切。市中心切得很细，沙漠里几乎不切，**自适应** 数据的密度。

### Geohash 是怎么编码的

1. 经度范围 `[-180, 180]`，纬度范围 `[-90, 90]`。
2. 从 **经度** 开始，经度、纬度 **交替** 二分：值 `>=` 中点取 1 并保留上半区间，否则取 0 并保留下半区间。
3. 每 5 个比特组成一个数字（0 到 31），用 base32 字母表 `0123456789bcdefghjkmnpqrstuvwxyz`（没有 a、i、l、o）转成一个字符。

例：`(57.64911, 10.40744)` 编码成 11 位是 `u4pruydqqvj`。字符串越长，格子越小：5 位约 4.9 km × 4.9 km，7 位约 153 m × 153 m，9 位约 4.8 m × 4.8 m。

**Geohash 的坑**：两个点挨得很近，但正好在格子边界两侧，前缀可能完全不同（比如赤道和本初子午线附近）。所以查附近时，**不能只查自己所在的格子，要把周围 8 个邻居格子也查了**。

## 要求

实现 `solution.py` 里的函数和两个类。

### 1. Geohash 函数

- `geohash_encode(lat, lon, precision=12) -> str`：按上面的规则编码。纬度不在 `[-90, 90]`、经度不在 `[-180, 180]`、`precision` 不在 `1..12` 里，抛 `ValueError`。
- `geohash_bbox(h) -> (min_lat, min_lon, max_lat, max_lon)`：这个 geohash 对应的格子边界。空字符串或含非法字符，抛 `ValueError`。
- `geohash_decode(h) -> (lat, lon, lat_err, lon_err)`：格子中心点，以及半高、半宽（误差范围）。
- `geohash_neighbors(h) -> dict`：同样长度的 8 个邻居，键为 `"n" "ne" "e" "se" "s" "sw" "w" "nw"`。
  - 做法：取格子中心，按方向移动一个格子的高度 / 宽度，再用同样的长度编码。
  - 经度要 **绕回**：从 179.9° 往东走一格，会到 -179.9° 附近（太平洋上的日期变更线两侧是邻居）。
  - 纬度不绕回：移动后的纬度 `<= -90` 或 `>= 90`（越过了极点），这个方向的邻居为 `None`。
- `haversine_km(lat1, lon1, lat2, lon2) -> float`：球面距离，地球半径用 `EARTH_RADIUS_KM = 6371.0`。

### 2. `GeoIndex()`：基于 Geohash 的附近搜索

- `add(item_id, lat, lon)`：加入一个点。`item_id` 已存在就更新它的位置（商家搬家了）。坐标非法抛 `ValueError`。
- `remove(item_id) -> bool`。`len(index)`：点的个数。
- `nearby(lat, lon, radius_km, limit=10) -> list[(item_id, distance_km)]`：返回距离 `<= radius_km` 的点，按 **距离从近到远** 排序（距离相同按 `item_id` 排），最多 `limit` 个。`radius_km <= 0` 或 `limit < 1` 抛 `ValueError`。
- 实现要求：
  - 每个点按 9 位 geohash 存进一个 **排好序的列表**（`bisect`），这就是你的「B+ 树索引」。
  - 查询时：选一个合适的 geohash 长度 `p`，让一个格子的高和宽都 **不小于** `radius_km`；算出查询点的 `p` 位 geohash 以及它的 8 个邻居；对这 9 个前缀分别在排序列表里做 **前缀范围扫描**；对扫出来的候选点用 `haversine_km` 精确过滤。
  - 估算格子的宽高：纬度 1 度约 111.32 km；经度 1 度约 `111.32 × cos(纬度)` km。注意越靠近两极，格子越窄。保险起见，宽度按 `cos(|lat| + radius_km / 111.32)` 来算（也就是按查询范围里最靠近极点的那个纬度）。
  - 想一想：为什么格子要 **不小于** 半径？如果格子比半径小，只查 3×3 个格子会漏掉什么？
  - **不能** 遍历所有点。测试会在 10 万个点上做 1000 次查询。

### 3. `QuadTree(capacity=8, bounds=(-90.0, -180.0, 90.0, 180.0))`：点四叉树

- `bounds` 是 `(min_lat, min_lon, max_lat, max_lon)`。`capacity < 1` 抛 `ValueError`。
- `insert(item_id, lat, lon)`：点不在 `bounds` 里抛 `ValueError`。
  - 叶子节点存点。一个叶子的点数 **超过** `capacity` 时，**分裂** 成 4 个子节点，并把点分配下去。深度到 `MAX_DEPTH = 20` 就不再分裂（否则同一个坐标上有很多点时会无限分裂）。
  - 分配规则：`lat >= 纬度中线` 去北边，否则南边；`lon >= 经度中线` 去东边，否则西边。
- `query_rect(min_lat, min_lon, max_lat, max_lon) -> list`：返回矩形内（含边界）所有点的 `item_id`，**排好序**。只进入和矩形相交的子树。
- `leaves() -> list[(bounds, count, depth)]`：所有叶子节点的边界、点数和深度（根节点深度为 0），顺序不限。
- `depth()`：最深的叶子的深度。`len(tree)`：点数。

## 接口

```python
geohash_encode(57.64911, 10.40744, 11)    # "u4pruydqqvj"
geohash_neighbors("u4pruyd")["n"]          # "u4pruyf"

idx = GeoIndex()
idx.add("cafe-1", 39.9087, 116.3975)
idx.nearby(39.91, 116.40, radius_km=1)     # [("cafe-1", 0.26...)]

qt = QuadTree(capacity=4)
qt.insert("a", 31.23, 121.47)
qt.query_rect(31, 121, 32, 122)            # ["a"]
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-14/1-geo-index
```

共 44 个测试。建议顺序：`-k geohash` → `-k haversine` → `-k index` → `-k quadtree`。

## 进阶（可选）

- 给四叉树加 `nearest(lat, lon, k)`：最近的 k 个点。用优先队列做 **最佳优先搜索**：按「点到格子的最短距离」把格子放进堆里，先展开最近的格子。什么时候可以提前停止？
- Google 的 **S2** 和 Uber 的 **H3** 用的不是矩形格子，而是把球面投影到立方体上再用希尔伯特曲线编码（S2），或者用六边形（H3）。它们解决了 Geohash 的哪些问题？
- 商家的位置很少变，但网约车司机每 4 秒上报一次位置。四叉树和 Geohash 索引，哪个更适合频繁更新？（Day 22 的打车系统会再讲）

## 面试追问（做完后自己先想想）

- 为什么 Geohash 能把二维查询变成一维的范围查询？这对存储选型有什么好处？
- 同样搜 1 km，在北京市中心和在新疆的戈壁上，候选点的数量会差多少？Geohash 和四叉树谁更能适应这种不均匀？
- 一个 9 位的 geohash 前缀查出来 10 万个候选点（比如国贸的写字楼里都是商家），怎么办？
- 四叉树放在内存里，1 亿个商家要多少内存？服务重启时怎么快速重建？
- 用户在地图上拖动，每次都发一次查询。怎么缓存查询结果？用户位置稍微变一点，缓存还能用吗？
