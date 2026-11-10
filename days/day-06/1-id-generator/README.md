# Day 06 · 动手题：Snowflake ID 生成器 + 号段分配器

## 背景

单机数据库里，主键用自增 ID 就够了。分库分表、多机房之后，自增 ID 不行了：每个库各自从 1 开始会重复。常见的替代方案：

| 方案 | 优点 | 缺点 |
|------|------|------|
| UUID v4（128 位随机） | 不用协调，永不冲突 | 太长；完全无序，当 B+ 树主键会导致页分裂、写放大 |
| 数据库号段（美团 Leaf-segment、Flickr ticket server） | 严格递增，好理解 | 依赖数据库；ID 连续，会暴露业务量 |
| **Snowflake**（Twitter） | 64 位整数，大致按时间递增，本地生成、不用网络 | 依赖机器时钟；时钟回拨会出重复 ID |

今天实现后两种。

### Snowflake 的 64 位布局

```
 0 | 41 位：毫秒时间戳（相对自定义纪元） | 5 位：数据中心 ID | 5 位：机器 ID | 12 位：序列号
63  62                                  22 21              17 16          12 11            0
```

- 最高位恒为 0，保证 ID 是正数。
- 41 位毫秒能用约 69 年，所以时间戳要减去一个 **自定义纪元**（比如项目上线那天），而不是从 1970 年开始算。
- 同一毫秒内用 12 位序列号区分，每台机器每毫秒最多 4096 个 ID。

### 号段模式（Leaf-segment）

数据库里存一行 `max_id`。每台 ID 服务器一次取一段（比如 1000 个）：`UPDATE ... SET max_id = max_id + 1000`，然后在内存里一个一个发。数据库压力降到原来的千分之一。再加上 **双缓冲**：当前号段快用完时就提前去取下一段，取号就不会因为等数据库而卡顿。

## 要求

实现 `solution.py` 里的 `Snowflake`、`parse_id` 和 `SegmentAllocator`。

### 1. `Snowflake(worker_id, datacenter_id=0, *, epoch_ms=DEFAULT_EPOCH_MS, clock=None, max_backward_ms=5)`

- `worker_id`、`datacenter_id` 必须在 `0..31` 之间，否则抛 `ValueError`。
- `clock` 是一个无参函数，返回当前 Unix 毫秒时间戳（`int`）。为 `None` 时用 `time.time_ns() // 1_000_000`。**所有取时间的地方都调用这个 `clock`**，测试用假时钟控制时间。
- `next_id()`：
  - 时间戳和上一次相同：序列号 +1。
  - 时间戳比上一次大：序列号归 0。
  - 同一毫秒 4096 个用完了：**反复调用 `clock()`，直到它返回一个更大的毫秒**，再用新毫秒发号（可以在循环里 `time.sleep(0)`，但不要 `sleep` 一个固定时间）。
  - **时钟回拨**（`clock()` 比上一次发号的毫秒小）：
    - 回拨幅度 `<= max_backward_ms`：反复调用 `clock()` 等它追上上一次的毫秒，再继续发号；
    - 回拨幅度更大：抛 `ClockMovedBackwardsError`（已经定义好了），**不能发出任何可能重复的 ID**。
  - 时间早于纪元，抛 `ValueError`；时间戳超出 41 位，抛 `OverflowError`。
  - 同一个实例发出的 ID **严格递增**。
  - **线程安全**：多个线程同时调用也不能重复。
- `parse_id(id, epoch_ms=DEFAULT_EPOCH_MS)` 返回 `SnowflakeParts(timestamp_ms, datacenter_id, worker_id, sequence)`，其中 `timestamp_ms` 是 **绝对的** Unix 毫秒（已经加回纪元）。

### 2. `SegmentAllocator(fetch_segment, step, *, prefetch_at=0.9)`

- `fetch_segment(step)` 是外部传入的函数，模拟数据库的 `UPDATE id_alloc SET max_id = max_id + step`，返回新号段的 **起点** `start`，这个号段就是 `[start, start + step)`。它可能抛异常（数据库挂了）。
- `step < 1` 或 `prefetch_at` 不在 `(0, 1]` 里，抛 `ValueError`。
- **构造时就取第一个号段**（取不到就让异常直接抛出去，尽早失败）。
- `next_id()`：
  - 从当前号段按顺序发号。当前号段用完了，就切换到备用号段；没有备用号段就当场去取一个。
  - 发出这个号 **之后**，如果当前号段已经用掉的个数 `>= ceil(step × prefetch_at)`，并且还没有备用号段，就去取一个备用号段（同步取即可）。
  - 预取失败时 **不要抛异常**，吞掉它，继续用当前号段；下一次 `next_id()` 时再按上面的规则重试。只有当前号段用完、又没有备用号段、当场取也失败时，才把异常抛给调用方。
  - **线程安全**。
- `fetch_count` 属性：一共成功调用了多少次 `fetch_segment`（含构造时那次）。

例子：`step=10, prefetch_at=0.9`，构造时取到 `[1, 11)`，`fetch_count == 1`。发出第 9 个号（ID 9）后，已用 9 个 `>= ceil(9.0)`，去预取 `[11, 21)`，`fetch_count == 2`。第 11 次调用时切到备用号段，返回 11。

## 接口

```python
gen = Snowflake(worker_id=3, datacenter_id=1)
i = gen.next_id()           # 例如 1859384051200004096 这样的 64 位正整数
parse_id(i)                 # SnowflakeParts(timestamp_ms=..., datacenter_id=1, worker_id=3, sequence=0)

alloc = SegmentAllocator(db_fetch, step=1000)
alloc.next_id()             # 1
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-06/1-id-generator
```

共 35 个测试。建议顺序：先 `-k "snowflake and not backward"`，再 `-k backward`（时钟回拨），最后 `-k segment`。

## 进阶（可选）

- 序列号每毫秒都从 0 开始，导致 QPS 不高时绝大多数 ID 的低 12 位都是 0。如果下游用 `id % 16` 分库，会怎样？怎么改？
- 把位数分配做成可配置（比如 39 位时间戳按 10 ms 为单位 + 8 位序列号 + 16 位机器 ID，这是 Sony 的 Sonyflake）。各自的上限是多少？
- 号段的预取改成后台线程异步取，`next_id()` 永远不等数据库。要注意哪些并发问题？
- 机器 ID 怎么分配才能保证全局唯一？试着用 Day 12 会实现的「带租约的锁」思路，写一个从注册中心领取 worker_id 的伪代码。

## 面试追问（做完后自己先想想）

- 这台机器一秒能发多少个 Snowflake ID？整个集群呢？41 位时间戳从你选的纪元开始还能用到哪一年？
- NTP 把时钟往回调了 2 秒，你的生成器会怎样？等 2 秒可以接受吗？还有什么别的办法（记住上次时间戳并持久化、借用未来时间、换一个备用 worker_id）？
- 进程重启后，上一次发号的时间戳丢了。如果重启很快、而重启期间时钟又回拨了，会不会发出重复 ID？怎么防？
- 号段模式下 ID 服务重启，内存里没发完的号段会怎样？这有问题吗？为什么号段的 ID 只能保证「趋势递增」而不是「严格递增」（有多台 ID 服务器的时候）？
- 订单号用 Snowflake，竞争对手每天下两单，就能算出你一天有多少订单吗？怎么防？
