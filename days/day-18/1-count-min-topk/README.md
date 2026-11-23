# Day 18 · 动手题：Count-Min Sketch + 热点 Top-K + 滑动窗口热搜

## 背景

「微博热搜」「抖音热榜」「Twitter Trends」要回答一个问题：**最近 5 分钟里，被搜索 / 提到最多的是哪几个词？**

最直接的办法是用一个哈希表给每个词计数，然后排序。可是每分钟有上亿次搜索，出现过的不同的词有几千万个，其中绝大多数只出现一两次。为了找出前 50 名，把几千万个冷门词都精确地存下来，内存和排序的代价都太大了。

今天用三个零件拼出一个热搜榜：

1. **Count-Min Sketch（CMS）**：一个 `depth × width` 的计数表。每个词在每一行用不同的哈希函数落到一个格子里，加一就把这 `depth` 个格子都加一；查询时取这 `depth` 个格子里的 **最小值**。不同的词可能撞到同一个格子，所以估计值 **只会偏大、不会偏小**。用固定的几十 KB 内存，就能给任意多个词计数。
2. **Top-K**：CMS 只能回答「某个词大概出现了多少次」，不能回答「哪些词最多」。所以旁边再维护一个最多 `k` 个词的 **候选集**：新来的词估计值超过候选集里最小的那个，就把最小的挤出去。热门词出现得多，总会进入候选集。
3. **滑动窗口**：热搜要的是「最近 5 分钟」，不是「有史以来」。把时间切成 1 分钟一个桶，每个桶一个 CMS 和一个 Top-K。查询时把窗口内的桶 **合并**（CMS 可以逐格相加），过期的桶直接整个扔掉。

## 要求

实现 `solution.py` 里的 `CountMinSketch`、`TopK` 和 `TrendingTracker`。

`item` 可以是 `str`（按 UTF-8 编码）或 `bytes`，其他类型抛 `TypeError`。第 `r` 行的列号 **必须** 用已经写好的 `row_index(item, r, width)`，测试会检查计数表里每一格的内容。

### 1. `CountMinSketch(width, depth, *, conservative=False)`

- `width < 1` 或 `depth < 1` 抛 `ValueError`。公开属性 `width`、`depth`、`conservative`，以及 `total`（加进去的 `count` 之和）。
- `from_error(epsilon, delta, *, conservative=False)`（类方法）：`epsilon`、`delta` 都必须在开区间 `(0, 1)` 里，否则抛 `ValueError`。`width = ceil(e / epsilon)`，`depth = ceil(ln(1 / delta))`。含义是：估计值超过真实值 `epsilon × total` 以上的概率不超过 `delta`。
- `add(item, count=1) -> int`：返回加完以后 `item` 的估计值。`count` 不是 `int` 抛 `TypeError`，是负数抛 `ValueError`，`0` 合法（什么都不变）。
  - 普通模式：`item` 在每一行对应的格子都加 `count`。
  - **保守更新**（`conservative=True`）：先算出当前估计值 `est`（各行格子的最小值），令 `new = est + count`，然后每一行的格子 `= max(格子当前值, new)`。只抬高「不够高」的格子，估计值仍然不会偏小，但碰撞带来的误差小很多。
- `estimate(item) -> int`：各行对应格子的最小值。
- `merge(other) -> CountMinSketch`：返回新对象，逐格相加，`total` 也相加。`width` 或 `depth` 不同抛 `ValueError`。不能修改两个输入。
- `table` 属性：返回计数表的副本（`depth` 个长度为 `width` 的列表）。

### 2. `TopK(k, sketch)`

- `k < 1` 抛 `ValueError`。`sketch` 是外部传入的 `CountMinSketch`，`TopK` 往里面加数据。
- `add(item, count=1) -> bool`：先 `sketch.add(item, count)` 得到估计值 `est`，然后：
  - `item` 已经在候选集里：返回 `True`。
  - 候选集还不到 `k` 个：加进去，返回 `True`。
  - 否则找出候选集里 **当前估计值最小** 的那个（估计值一样时取字典序最小的）。如果 `est` **严格大于** 它的估计值，就用 `item` 把它换掉，返回 `True`；否则返回 `False`。
- `candidates() -> set`：候选集的副本。
- `top(n=None) -> list[(item, estimate)]`：候选集里每个词的 **当前** 估计值，按估计值降序、相同时按 `item` 升序排列。给了 `n` 就只返回前 `n` 个。

### 3. `TrendingTracker(k, width, depth, *, window=300.0, bucket=60.0, clock=time.monotonic)`

- `k < 1`、`bucket <= 0`、`window <= 0`，或者 `window` 不是 `bucket` 的整数倍，抛 `ValueError`。窗口里有 `n = window / bucket` 个桶。
- 时间 `t` 属于第 `floor(t / bucket)` 号桶。当前桶号为 `cur` 时，只有桶号在 `(cur - n, cur]` 里的桶还活着，其余的删除（每次调用时惰性清理）。
- 每个桶有自己的 `TopK(k, CountMinSketch(width, depth))`，第一次往这个桶里加数据时才创建。
- `add(item, count=1)`：加到当前桶里。
- `live_buckets() -> int`：当前还活着的、已经创建了的桶的个数。
- `estimate(item) -> int`：把所有活着的桶的 CMS 合并以后的估计值。
- `trending(n=None) -> list[(item, estimate)]`：候选词 = 所有活着的桶的候选集的 **并集**；用合并后的 CMS 给它们估计，按估计值降序、相同时按 `item` 升序，最多返回 `k` 个（给了 `n` 再截到 `n` 个）。

做之前，先自己想明白：为什么 CMS 的估计只会偏大？为什么要取多行里的最小值，而不是平均值？

## 接口

```python
s = CountMinSketch.from_error(0.001, 0.01)   # 2719 × 5 个计数器
s.add("世界杯")
s.estimate("世界杯")                         # >= 真实次数

t = TopK(10, s)
for q in search_log: t.add(q)
t.top()                                     # [("世界杯", 98213), ...]

tr = TrendingTracker(50, 2719, 5, window=300, bucket=60)
tr.add("世界杯")
tr.trending(10)                             # 最近 5 分钟的前 10 名
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-18/1-count-min-topk
```

共 33 个测试。建议顺序：`-k cms` → `-k topk` → `-k trend`。

## 进阶（可选）

- `TopK.add` 每次都在 `k` 个候选里线性找最小值。改成 **最小堆**，候选的估计值会在背后变大（别的词碰撞进来），堆还正确吗？怎么处理？
- 「热搜」其实不是「次数最多」，而是「**比平时多得多**」：「天气」每天都被搜很多次，不该一直挂在榜上。怎么用「这 5 分钟的次数 / 过去 24 小时同一时段的平均次数」来打分？
- 现在每个桶都是一个完整的 CMS。窗口是 24 小时、桶是 1 分钟的话就要 1440 个。怎么做多级桶（最近 1 小时按分钟、更早的按小时合并）？
- 分布式：100 台服务器各自维护一个 CMS，怎么汇总成全局的热搜？CMS 可以合并，Top-K 的候选集能直接合并吗？

## 面试追问（做完后自己先想想）

- CMS 和 Day 4 的布隆过滤器有什么相同和不同？它们为什么都只会「偏一个方向」地出错？
- 为什么 CMS 对 **热门词** 估计得很准、对 **冷门词** 估计得很不准？这对「找热点」这个问题是好事还是坏事？
- CMS 能处理「减一」（比如删除一条搜索记录）吗？减了以后「只会偏大」还成立吗？保守更新还能用吗？
- 精确的 Top-K 需要多少内存？和 CMS + 候选集比，用一台机器 64 GB 内存能不能直接精确地算？什么时候才真正需要近似算法？
