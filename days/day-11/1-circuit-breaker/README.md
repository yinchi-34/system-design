# Day 11 · 动手题：熔断器 + 指数退避重试 + 重试预算

## 背景

微服务之间互相调用，下游总会偶尔失败：网络抖动、对方在发布、对方过载。最朴素的应对是「失败了就重试」，但不加控制的重试会把小故障放大成大事故：

- **重试风暴**：下游已经过载，每个上游都立刻重试 3 次，下游的流量瞬间变成 4 倍，彻底被打死。调用链有 5 层、每层重试 3 次，最底层的流量会放大到 3⁵ = 243 倍。
- **惊群**：1 万个客户端同一时刻失败，都等 1 秒后重试，1 秒后又同时打过来。→ **退避要加随机抖动**（jitter）。
- **一直打一个已经挂了的服务**：每个请求都要等 5 秒超时，线程池被占满，上游也跟着挂（级联故障）。→ **熔断器**：失败太多就「跳闸」，一段时间内直接快速失败，不再调用下游；过一会儿放几个请求「试探」，恢复了再合闸。

今天实现这三件套。它们正是今天设计题「支付系统」调用银行和第三方支付渠道时必须用到的。

## 要求

实现 `solution.py` 里的 `compute_backoff`、`RetryBudget`、`retry` 和 `CircuitBreaker`。所有时间都通过注入的 `clock()` 获取，所有等待都通过注入的 `sleep()` 完成，测试里不会真的睡。

### 1. `compute_backoff(attempt, *, base, cap, jitter="full", rng=None) -> float`

第 `attempt` 次失败后（从 1 开始），下一次重试前要等多久：

- 先算指数部分：`exp = min(cap, base × 2^(attempt-1))`。
- 按 `jitter` 加随机：
  - `"none"`：返回 `exp`。
  - `"full"`：返回 `rng.uniform(0, exp)`。
  - `"equal"`：返回 `exp / 2 + rng.uniform(0, exp / 2)`。
- `rng` 为 `None` 时用 `random` 模块。带随机的两种模式 **只能调用一次** `rng.uniform`，参数必须和上面一样（测试会用同一个种子的 `random.Random` 对比结果）。
- `attempt < 1`、`base <= 0`、`cap < base`、`jitter` 不认识，都抛 `ValueError`。

AWS 有一篇著名的文章《Exponential Backoff And Jitter》比较了这几种抖动，做完后可以去读一下。

### 2. `RetryBudget(*, ratio=0.1, min_retries=10, window=10.0, clock=time.monotonic)`

**重试预算**：在最近 `window` 秒内，重试次数不能超过「请求数 × `ratio`」，但至少允许 `min_retries` 次（流量很小时也能重试）。这样下游大面积故障时，重试流量最多只占正常流量的 10%，不会形成重试风暴。（Finagle、gRPC、Envoy 都有类似机制。）

- `record_request()`：记录一次「原始请求」（第一次尝试，不含重试）。
- `try_acquire_retry() -> bool`：如果最近 `window` 秒内的重试次数 `< max(min_retries, ratio × 最近 window 秒内的请求数)`，记录一次重试并返回 `True`；否则返回 `False`。
- 「最近 `window` 秒」指时间戳 `t` 满足 `now - window < t <= now` 的事件。
- `ratio < 0`、`min_retries < 0`、`window <= 0` 抛 `ValueError`。

### 3. `retry(func, *, max_attempts=3, base=0.1, cap=10.0, jitter="full", retry_on=(Exception,), sleep=time.sleep, rng=None, budget=None)`

- 调用 `func()`（无参数），成功就返回它的结果。
- 抛出的异常是 `retry_on` 里的类型时：
  - 如果已经试了 `max_attempts` 次，把 **最后一次的异常** 原样抛出；
  - 如果给了 `budget` 并且 `budget.try_acquire_retry()` 返回 `False`，同样把这个异常原样抛出；
  - 否则 `sleep(延迟)` 后再试。延迟用 `compute_backoff(第几次失败, base=..., cap=..., jitter=..., rng=...)` 算；如果异常对象有 `retry_after` 属性且不为 `None`（比如 HTTP 429 / 503 的 `Retry-After` 头，或者下面熔断器抛的异常），延迟取两者中的 **较大值**。
- 不在 `retry_on` 里的异常（比如参数错误、余额不足这类业务错误）**不重试**，直接抛出。
- 给了 `budget` 时，每次调用 `retry()` 开始时调用一次 `budget.record_request()`。
- `max_attempts < 1` 抛 `ValueError`。

### 4. `CircuitBreaker(*, failure_threshold=5, recovery_timeout=30.0, half_open_max_calls=1, failure_exceptions=(Exception,), clock=time.monotonic, on_state_change=None)`

三种状态（常量已定义好）：`CLOSED`（正常）、`OPEN`（跳闸）、`HALF_OPEN`（试探）。

- `call(func, *args, **kwargs)`：通过熔断器调用 `func`，返回它的结果或者抛出它的异常。
- **CLOSED**：正常调用。连续失败 `failure_threshold` 次就转为 OPEN。成功一次就把连续失败计数清零。属性 `failure_count` 是当前的连续失败次数。
- **OPEN**：**不调用** `func`，直接抛 `CircuitOpenError`，它的 `retry_after` 属性是距离可以试探还剩多少秒。从进入 OPEN 开始过了 `recovery_timeout` 秒（`now >= 进入时间 + recovery_timeout`），自动转为 HALF_OPEN（惰性判断：在下一次 `call` 或读 `state` 时转换）。
- **HALF_OPEN**：最多放行 `half_open_max_calls` 个试探调用。
  - 放行名额用完以后（还没出结果、或者已经成功但还没凑够）再来的调用，直接抛 `CircuitOpenError`（`retry_after` 为 0）。
  - 试探调用 **全部成功**（凑够 `half_open_max_calls` 次成功）就转为 CLOSED；**任何一次失败** 立刻转回 OPEN，重新计时。
- 什么算失败：抛出 `failure_exceptions` 里的异常。其他异常（比如业务上的「订单不存在」）**不算** 下游故障，按成功处理，但仍然原样抛给调用方。
- `state` 属性返回当前状态（先做惰性的时间转换）。
- `on_state_change(old, new)`：每次状态真正变化时调用一次。
- `reset()`：人工强制合闸，转为 CLOSED，计数清零。
- 参数不合法（`failure_threshold < 1`、`recovery_timeout <= 0`、`half_open_max_calls < 1`）抛 `ValueError`。
- **线程安全**：内部状态用锁保护，但是 **不要在持有锁的时候调用 `func`**（`func` 可能很慢，会把所有调用都串行化；`func` 里也可能再次调用同一个熔断器，导致死锁）。

## 接口

```python
cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10)
cb.call(requests.get, "https://bank.example.com/pay")

result = retry(lambda: cb.call(charge_card, order),
               max_attempts=4, base=0.2, cap=5,
               retry_on=(TimeoutError, CircuitOpenError))
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-11/1-circuit-breaker
```

共 46 个测试。建议顺序：`-k backoff` → `-k budget` → `-k retry` → `-k breaker`。

## 进阶（可选）

- 实现 AWS 文章里的第四种抖动 **decorrelated jitter**：`sleep = min(cap, uniform(base, 上一次的 sleep × 3))`。它为什么比 full jitter 更适合长时间的重试？
- 把熔断条件从「连续失败 N 次」改成「最近 10 秒内请求数 ≥ 20 且失败率 ≥ 50%」（Hystrix / resilience4j 的做法）。为什么连续失败计数在高流量下不太好用？
- 「慢调用」也算失败：调用耗时超过某个阈值就计入失败。为什么慢比失败更危险？
- 熔断器是每个进程一份，还是整个集群共享一份？各有什么问题？

## 面试追问（做完后自己先想想）

- 什么样的错误应该重试，什么样的不应该？支付接口超时了，能不能直接重试？（提示：明天之前先想想 **幂等**，今天的设计题会重点讨论）
- 调用链 A → B → C，三层都各自重试 3 次，C 挂了时 C 收到的请求是正常的多少倍？应该在哪一层重试？
- 熔断器打开后，用户看到的是什么？除了直接报错，还有哪些 **降级** 方案（返回缓存、返回默认值、排队稍后处理）？
- 熔断器、限流器（Day 3）、超时、舱壁隔离（bulkhead），各自防的是什么问题？
