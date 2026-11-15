# Day 13 · 动手题：分片计数器 + 缓冲聚合 + HyperLogLog

## 背景

「点赞数 +1」「播放量 +1」看起来是最简单的写操作：`UPDATE posts SET likes = likes + 1 WHERE id = ?`。但一条爆款视频每秒被点赞几万次时，这一行就成了全系统最热的一行：

- **行锁争用**：所有更新排队等同一把行锁，数据库每秒只能处理几百到一千次单行更新（Day 12 秒杀里的库存行也是同样的问题）。
- **写放大**：每次 +1 都是一次完整的事务、一次 WAL 写入（Day 5）、一次复制（Day 8）。

工业界常用三招，今天各实现一个：

1. **分片计数器**（sharded counter）：把一个计数拆成 N 个分片，每次随机挑一个分片 +1，读的时候把 N 个分片加起来。写争用降为原来的 1/N，代价是读要读 N 次。Google App Engine 的官方文档就专门讲过这个模式。
2. **缓冲聚合**（write-behind / batching）：在应用服务器内存里先攒着，「视频 A +37、视频 B +5」每秒刷一次到存储。1 万次 +1 变成 1 次 +10000。代价是进程崩溃时会丢掉还没刷的部分，计数也会有几秒延迟。
3. **HyperLogLog**：播放量常常要的是「**多少个不同的人** 看过」（UV），而不是「被看了多少次」（PV）。精确去重要存下每个用户 ID，一亿个用户就是几百 MB；HyperLogLog 只用 **12 KB** 就能估算到误差 1% 以内。Redis 的 `PFADD` / `PFCOUNT` 就是它。

## 要求

实现 `solution.py` 里的 `ShardedCounter`、`BufferedCounter` 和 `HyperLogLog`。

### 1. `ShardedCounter(num_shards, *, rng=None)`

- `num_shards < 1` 抛 `ValueError`。`rng` 是 `random.Random` 实例，`None` 时自己新建一个。
- `increment(key, delta=1) -> int`：用 `rng.randrange(num_shards)` 挑一个分片（**每次调用恰好调用一次** `randrange`，测试会用同种子的随机数对比），把 `delta` 加到这个分片上，返回分片编号。`delta` 不是 `int` 抛 `TypeError`（可以是负数，比如取消点赞）。
- `get(key) -> int`：所有分片之和，不存在的 key 是 0。
- `shards(key) -> list[int]`：每个分片上的值，长度为 `num_shards`。
- `num_shards` 属性。
- **线程安全**：每个分片一把锁（而不是整个计数器一把大锁，否则分片就白分了）。注意 `random.Random` 本身也不是为多线程设计的。

### 2. `BufferedCounter(sink, *, flush_interval=1.0, max_keys=1000, clock=time.monotonic)`

- `sink(batch: dict[key, int])` 是外部传入的函数，代表一次批量写存储（比如一条 `UPDATE ... CASE` 或 Redis pipeline）。它可能抛异常。
- `flush_interval <= 0` 或 `max_keys < 1` 抛 `ValueError`。构造时记下 `last_flush = clock()`。
- `increment(key, delta=1)`：把 `delta` 累加到内存缓冲里。如果某个 key 的累计值变成 0（点赞后又取消），就从缓冲里删掉这个 key。然后，如果 `clock() - last_flush >= flush_interval`，或者缓冲里的 key 数 `>= max_keys`，就调用 `flush()`。**`increment` 永远不能因为 `sink` 出错而抛异常**（计数失败不能让用户的点赞请求报错），但失败要被记录下来。`delta` 不是 `int` 抛 `TypeError`。
- `flush() -> int`：
  - 把 `last_flush` 更新为 `clock()`（不管成功失败，避免存储挂了的时候每次 increment 都去重试）。
  - 缓冲为空就什么都不做，返回 0（**不调用** `sink`）。
  - 否则把整个缓冲 **一次性** 交给 `sink`（传一个副本），成功后清空缓冲，返回 key 的个数。
  - `sink` 抛异常时：**这批数据不能丢，也不能重复**，要合并回缓冲（和失败期间新来的增量相加），`failed_flushes` 加 1，然后把异常抛出去。
- `pending(key) -> int`：缓冲里还没刷出去的增量。
- `failed_flushes` 属性：失败的次数。
- `close() -> int`：等同于 `flush()`，进程退出前调用。
- **线程安全**；同样，**不要在持有锁的时候调用 `sink`**（它可能很慢）。

### 3. `HyperLogLog(p=14)`

- `p` 是精度，取值 `4..16`，否则抛 `ValueError`。寄存器个数 `m = 2^p`，每个寄存器 1 字节，用一个长度为 `m` 的 `bytearray`，初始全 0。
- **哈希**（必须完全按这个来，测试会检查寄存器的内容）：
  - `str` 按 UTF-8 编码，`bytes` 原样，其他类型抛 `TypeError`；
  - `x = int.from_bytes(hashlib.sha1(data).digest()[:8], "big")`，一个 64 位整数。
- `add(item) -> bool`：
  - 寄存器下标 `idx` = `x` 的 **最高 `p` 位**；
  - 剩下的低 `64 - p` 位记为 `w`，`rho` = `w` 里 **从最高位数起第一个 1 的位置**（从 1 开始数；`w` 全为 0 时 `rho = 64 - p + 1`）。提示：`int.bit_length()`；
  - `registers[idx] = max(registers[idx], rho)`。寄存器有变化返回 `True`，否则返回 `False`（和 Redis 的 `PFADD` 一样）。
- `count() -> int`：
  - `alpha`：`m = 16` 时 0.673，`m = 32` 时 0.697，`m = 64` 时 0.709，其余为 `0.7213 / (1 + 1.079 / m)`；
  - 原始估计 `E = alpha × m² / Σ 2^(-registers[j])`；
  - **小基数修正**：如果 `E <= 2.5 m` 并且有 `V > 0` 个寄存器是 0，改用线性计数 `E = m × ln(m / V)`；
  - 返回 `round(E)`（整数）。空的返回 0。
- `merge(other) -> HyperLogLog`：返回新对象，每个寄存器取两者的最大值（不修改输入）。`p` 不同抛 `ValueError`。这就是「按小时统计的 UV 合并成按天的 UV」的方法。
- `registers` 属性：返回寄存器内容的 `bytes` 副本。

做之前，先自己想明白：为什么「见过的最长前导零」能用来估计基数？为什么要分成 `m` 个桶再取调和平均，而不是只用一个寄存器？

## 接口

```python
c = ShardedCounter(16)
c.increment("video:42")
c.get("video:42")              # 1

b = BufferedCounter(lambda batch: db.bulk_add(batch), flush_interval=1)
b.increment("video:42")        # 先攒着，1 秒后（下一次 increment 时）一起刷

h = HyperLogLog(14)            # 16 KB 寄存器
for uid in viewers: h.add(uid)
h.count()                      # 误差约 1.04 / sqrt(16384) ≈ 0.8%
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-13/1-counters
```

共 29 个测试。建议顺序：`-k sharded` → `-k buffered` → `-k hll`。

## 进阶（可选）

- 分片数固定的话，冷门视频也要占 N 个分片。改成「按热度动态分片」：平时 1 个分片，检测到写入速率超过阈值时扩成 16 个。扩容的瞬间怎么保证计数不丢？
- `BufferedCounter` 进程崩溃会丢最多 `flush_interval` 秒的数据。如果点赞数必须精确（比如带奖励的点赞活动），怎么改？（先写日志 / 消息队列，再异步聚合）
- 给 HyperLogLog 加上 **稀疏表示**：基数很小时只存非零的寄存器（Redis 就是这么做的），内存能省多少？什么时候转成稠密表示？
- HyperLogLog 能做 **交集** 吗？「同时看过视频 A 和视频 B 的人数」能用容斥原理 `|A∪B| = |A| + |B| - |A∩B|` 算吗？误差会怎样？

## 面试追问（做完后自己先想想）

- 分片计数器的 `get` 要读 N 个分片。如果读也很频繁（每次展示视频都要显示点赞数），怎么办？（缓存一个汇总值，几秒过期）
- 点赞数允许有几秒延迟，但「我有没有点过赞」（按钮是否高亮）必须马上正确。这两者为什么要分开存储？
- HyperLogLog 的标准误差是 `1.04 / sqrt(m)`。要把误差降到 0.1%，需要多少内存？什么场景下 HLL 不适用（必须精确的场景）？
- 「播放量」怎么防刷（同一个人反复刷新）？去重是在计数之前还是之后？用 HLL 还是用布隆过滤器（Day 4）？它们回答的问题有什么区别？
