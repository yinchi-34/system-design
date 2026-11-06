# Day 03 · 动手题：限流器（令牌桶 + 滑动窗口）

## 背景

几乎所有对外的 API 都有限流：GitHub API 每小时 5000 次、Twitter 发推每天有上限、登录接口失败 5 次要等一会儿。限流的作用是保护后端不被突发流量或恶意脚本打垮，同时让多个租户公平地共享资源。

面试里「设计一个限流器」是高频题，考的是你能不能讲清楚几种算法的差别：

| 算法 | 内存 | 精确度 | 是否允许突发 | 谁在用 |
|------|------|--------|-------------|--------|
| 固定窗口计数 | O(1) | 窗口交界处能放过 2 倍流量 | 是（交界处） | 简单场景 |
| 滑动窗口日志 | O(limit) | 精确 | 否 | 对精度要求高、量小的场景 |
| 滑动窗口计数 | O(1) | 近似（假设上一窗口内请求均匀分布） | 很少 | Cloudflare |
| 令牌桶 | O(1) | 精确控制平均速率 | 是，最多 capacity 个 | AWS API Gateway、Stripe、Guava RateLimiter |

今天实现后三种。全部是 **单机、单个 key** 的版本，明天以后的设计题会把它扩展到分布式。

## 要求

实现 `solution.py` 里的三个类。所有时间都通过注入的 `clock()` 获取（单位是秒），测试用假时钟精确控制时间。**不要开后台线程或定时器**，状态在每次调用时按流逝的时间惰性更新（和 Day 1 的 TTL 惰性删除是一个思路）。

### 1. `TokenBucket(capacity, refill_rate, clock)`

- 桶最多装 `capacity` 个令牌，每秒补充 `refill_rate` 个，**令牌可以是小数**（0.5 秒补 1 个令牌的一半）。
- 创建时桶是 **满的**。
- `capacity <= 0` 或 `refill_rate <= 0` 抛 `ValueError`。
- `allow(cost=1)`：令牌 >= `cost` 时扣掉 `cost` 个并返回 `True`；不够时返回 `False`，**一个令牌也不扣**。
- `cost <= 0` 或 `cost > capacity`（永远不可能满足）时，`allow` 和 `retry_after` 都抛 `ValueError`。
- `tokens` 属性：返回当前令牌数（读之前先补充）。
- `retry_after(cost=1)`：还要等多少秒才能凑够 `cost` 个令牌，够了返回 `0`。它只是查询，不扣令牌。HTTP 429 响应里的 `Retry-After` 头就是用它算的。
- 令牌数不能超过 `capacity`：一小时没人访问，桶里也只有 `capacity` 个。
- **时钟回拨**（`clock()` 比上次小）时不能崩溃，也不能补出负数令牌：当作没有流逝时间处理。

### 2. `SlidingWindowLog(limit, window, clock)`

- 任意时刻 `now`，在窗口 `(now - window, now]` 内最多放行 `limit` 个请求。注意是 **左开右闭**：`t` 时刻放行的请求，到 `t + window` 那一刻正好过期。
- `limit < 1` 或 `window <= 0` 抛 `ValueError`。
- `allow()`：放行就记录这次的时间戳并返回 `True`，否则返回 `False`。**被拒绝的请求不记录**。
- `retry_after()`：还要等多少秒才能放行下一个请求，能放行就返回 `0`。
- `len(limiter)`：当前窗口内已放行的请求数。
- 内部最多只保存 `limit` 个时间戳（测试会检查），单次 `allow` 均摊 O(1)。提示：`collections.deque`，别用 `list.pop(0)`。

### 3. `SlidingWindowCounter(limit, window, clock)`

用两个固定窗口的计数器近似滑动窗口，内存 O(1)。

- 固定窗口 **按 `window` 的整数倍对齐**：时刻 `t` 落在编号为 `floor(t / window)` 的窗口里，这个窗口从 `编号 × window` 开始。
- 只保留「当前窗口」和「上一个窗口」两个计数。
- `estimated_count()` = `上一窗口计数 × (1 - (now - 当前窗口起点) / window) + 当前窗口计数`。
  - 例：`window=10`，`[1000, 1010)` 放行了 10 个，现在是 1012.5，当前窗口放行了 2 个，那么估算值是 `10 × 0.75 + 2 = 9.5`。
  - 如果时间已经跨过了不止一个窗口（中间有整个窗口没有请求），上一窗口计数视为 0。
- `allow()`：`estimated_count() + 1 <= limit` 时当前窗口计数加 1 并返回 `True`，否则返回 `False`（不计数）。
- `limit < 1` 或 `window <= 0` 抛 `ValueError`。
- 这一个不用考虑时钟回拨。

## 接口

```python
bucket = TokenBucket(capacity=10, refill_rate=2)   # 平均每秒 2 个，最多突发 10 个
bucket.allow()            # True
bucket.allow(cost=5)      # 一个请求消耗 5 个令牌，比如批量接口
bucket.retry_after()      # 0.0 或者要等的秒数

log = SlidingWindowLog(limit=100, window=60)       # 每分钟最多 100 个
log.allow()

counter = SlidingWindowCounter(limit=100, window=60)
counter.allow()
counter.estimated_count()
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-03/1-rate-limiter
```

共 42 个测试。建议按类分开做，比如先 `pytest days/day-03 -k bucket`，再 `-k log`，最后 `-k counter`。最后一个测试把三种算法放在同样的洪水流量下对照，看看它们放行的数量差在哪里。

## 进阶（可选）

- 写一个 `KeyedRateLimiter(factory, max_keys)`：按 key（用户 ID、IP）分别限流，每个 key 一个限流器实例。key 太多会撑爆内存，怎么回收长期不活跃的 key？（提示：Day 1 的 LRU。被回收的 key 下次来时是满桶，这样有问题吗？）
- 给 `TokenBucket` 加锁，开 8 个线程并发 `allow()`，验证放行总数没有超。不加锁时能复现超发吗？
- 实现「漏桶」（leaky bucket）：请求进队列，按固定速率流出。它和令牌桶的区别是什么？Nginx 的 `limit_req` 用的是哪种？

## 面试追问（做完后自己先想想）

- 令牌桶的两个参数 `capacity` 和 `refill_rate` 分别控制什么？如果业务说「每秒最多 10 个，不允许任何突发」，参数怎么设？
- 固定窗口在交界处能放过多少流量？滑动窗口计数的误差最大是多少？在什么流量分布下最不准？
- 为什么被拒绝的请求不应该计数（或者不应该消耗令牌）？反过来，有没有场景应该计数？（想想登录失败限流）
- 这些实现都靠惰性更新，没有后台线程。如果有 1000 万个 key，后台线程定时补令牌的方案会有什么问题？
- 单机限流放到 10 台机器上，每台配置为 1/10 的额度，会遇到什么问题？（这就是今天设计题要解决的）
