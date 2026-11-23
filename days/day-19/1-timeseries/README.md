# Day 19 · 动手题：时间序列降采样、计数器速率、分级存储、告警规则

## 背景

监控系统（Prometheus、InfluxDB、阿里云监控、Datadog）里的数据长这样：

```
http_requests_total{service="order", host="web-01"}   每 10 秒一个点
cpu_usage{host="web-01"}                              每 10 秒一个点
```

一万台机器、每台几百个指标，每 10 秒采一次，一天就是几百亿个点。这些数据有几个特点，决定了它和普通数据库很不一样：

- **越老的数据越没人看细节**：昨天 10 点 03 分 20 秒的 CPU 是多少没人关心，但「上个月每小时的平均 CPU」会有人看。所以老数据要 **降采样**：原始点只保留 1 小时，之后合并成每分钟一个点，再往后合并成每小时一个点。
- **降采样不能只存平均值**：只存每分钟的平均值，以后就算不出「每小时的最大值」，也算不对「每小时的平均值」（每分钟点数不一样时，平均值的平均值是错的）。要存 `count / sum / min / max`，它们可以 **合并**。
- **计数器只增不减，但会重置**：`http_requests_total` 是从进程启动开始的累计请求数，进程一重启就从 0 开始。要算「每秒多少请求」，就得处理重置。
- **告警不能一抖就报**：CPU 冲到 95% 一秒钟就下来，不应该半夜把人叫醒。所以规则里有一个 `for: 5m`：条件 **持续** 满足 5 分钟才真正告警。

## 要求

实现 `solution.py` 里的所有函数和类。时间戳一律是整数秒，值是 `int` 或 `float`。

### 1. `Agg(count, sum, min, max)` 和 `downsample(points, step, agg="avg")`

- `Agg.of(v)`：只有一个点 `v` 的聚合。`a.merge(b)`：合并两个聚合，返回新的 `Agg`。
- `a.value(agg)`：`agg` 是 `"avg"`（`sum / count`）、`"sum"`、`"min"`、`"max"`、`"count"` 之一。
- `downsample(points, step, agg)`：`points` 是 `(ts, value)` 的可迭代对象，**不一定有序**。每个点归到 `ts // step * step` 这个桶。返回 `[(桶起点, 聚合值), ...]`，按桶起点升序，只返回有数据的桶。`step <= 0` 或 `agg` 不认识抛 `ValueError`。

### 2. 计数器

- `counter_increase(points)`：先按时间排序。相邻两个点，后一个 `>=` 前一个时增量是差值；后一个 **更小**，说明计数器重置过，增量就是后一个点的值（从 0 涨上来的）。返回总增量。少于 2 个点返回 `None`。
- `counter_rate(points)`：`总增量 / (最后一个点的时间 - 第一个点的时间)`。少于 2 个点或者时间差为 0，返回 `None`。

### 3. `TimeSeriesDB(*, raw_retention=3600, rollup_step=60, rollup_retention=30*86400, clock=time.time)`

两级存储：原始点 + 按 `rollup_step` 聚合的 `Agg`。

- `raw_retention <= 0`、`rollup_step <= 0`，或者 `rollup_retention <= raw_retention`，抛 `ValueError`。
- `add(series, ts, value)`：`ts` 不是 `int`（`bool` 也不行）或者 `value` 不是数字（`bool` 也不行），抛 `TypeError`。`ts < clock() - raw_retention`（太老了，已经过了原始数据保留期）抛 `ValueError`。同一条序列、同一个时间戳再写一次就覆盖。
- `compact() -> int`：令 `cut = clock() - raw_retention`。
  - 每条序列里 `ts < cut` 的原始点，合并进它所在的 rollup 桶（`ts // rollup_step * rollup_step`；桶里已经有数据就 `merge`），然后删掉原始点。返回这次折叠的点数。
  - rollup 桶的 **结束时间**（`桶起点 + rollup_step`）`<= clock() - rollup_retention` 的，删除。
- `raw_count()`、`rollup_count()`：所有序列加起来的原始点数和 rollup 桶数。
- `series() -> list[str]`：还有数据（原始点或 rollup 桶）的序列名，升序。
- `raw_points(series, start, end)`：`start <= ts < end` 的原始点，按时间升序。
- `query(series, start, end, step, agg="avg")`：
  - `step` 必须是 `rollup_step` 的正整数倍，`agg` 必须认识，否则抛 `ValueError`。
  - 取 `start <= ts < end` 的原始点，和 **起点** 满足 `start <= 桶起点 < end` 的 rollup 桶，按 `ts // step * step` 归到输出桶里合并，返回格式和 `downsample` 一样。
  - **关键性质**：`compact()` 前后查询同一个范围，结果必须一样（`avg` 允许浮点误差）。

### 4. `AlertRule(name, op, threshold, *, for_seconds=0)`

- `op` 是 `">"`、`">="`、`"<"`、`"<="` 之一，`for_seconds < 0`，都抛 `ValueError`。
- 公开属性：`state`（`"inactive"` / `"pending"` / `"firing"`，初始 `"inactive"`）、`since`（进入 pending 的时间，否则 `None`）、`events`（列表）。
- `evaluate(ts, value) -> state`：每隔一段时间用最新的值评估一次。`ts` 比上一次评估的 **小** 抛 `ValueError`（相等可以）。
  - `value` 是 `None`（没有数据）或者条件不满足：如果当前是 `firing`，往 `events` 里追加 `("resolved", ts)`。然后回到 `inactive`，`since = None`。
  - 条件满足：如果是 `inactive`，进入 `pending`，`since = ts`。如果是 `pending` 且 `ts - since >= for_seconds`，进入 `firing`，追加 `("firing", ts)`。已经是 `firing` 就保持，**不重复** 追加事件。
  - 注意 `for_seconds = 0` 时，第一次满足条件就直接进入 `firing`。

做之前，先自己想明白：为什么 `count` 降采样两次时，第二次要用 `sum`？为什么 `p99` 不在 `AGGS` 里？

## 接口

```python
downsample([(0, 1), (5, 3), (10, 10)], 10)      # [(0, 2.0), (10, 10.0)]
counter_rate([(0, 100), (10, 150), (20, 30)])    # 进程重启过：(50 + 30) / 20 = 4.0

db = TimeSeriesDB(raw_retention=3600, rollup_step=60)
db.add("cpu{host=web-01}", 1700000000, 0.42)
db.compact()                                      # 后台每分钟跑一次
db.query("cpu{host=web-01}", start, end, 300, "max")

rule = AlertRule("HighCPU", ">", 0.9, for_seconds=300)
rule.evaluate(now, latest_cpu)                    # "pending" ... 5 分钟后 "firing"
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-19/1-timeseries
```

共 39 个测试。建议顺序：`-k "agg or downsample"` → `-k counter` → `-k db` → `-k alert`。

## 进阶（可选）

- 再加一级：每分钟的 rollup 保留 30 天，之后合并成每小时，保留 2 年。`query` 怎么决定读哪一级？
- 时间序列压缩：相邻时间戳的差值几乎都一样（都是 10 秒），相邻的值也很接近。Facebook 的 Gorilla 论文用 delta-of-delta 和 XOR 编码，平均每个点只要 1.37 字节。试着实现时间戳部分的 delta-of-delta 编码。
- `p99` 不能用 `count/sum/min/max` 合并。怎么存一个可以合并的分位数摘要？（直方图分桶、t-digest、DDSketch）
- 告警规则现在一条一条地评估。一万条规则、每条规则要查一次数据库，怎么减少查询？

## 面试追问（做完后自己先想想）

- 为什么监控数据适合用专门的时序数据库，而不是 MySQL 一张 `(series, ts, value)` 的表？写入模式、查询模式、删除模式分别有什么特点？
- 「标签」组合太多会怎样？比如有人把 `user_id` 当成标签，一个指标就变成了几千万条序列（高基数问题）。
- `for_seconds` 设长了和设短了，各有什么问题？告警的「漏报」和「误报」怎么权衡？
- 监控系统自己挂了，谁来告警？
