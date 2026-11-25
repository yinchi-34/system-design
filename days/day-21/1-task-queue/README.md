# Day 21 · 动手题：延迟队列 + 优先级调度 + 租约 + 退避重试

## 背景

很多事情不是「现在马上做」，而是「过一会儿再做」或者「到点了做」：

- 订单 15 分钟没支付，自动取消，释放库存（Day 20 酒店预订）；
- 发货 7 天后自动确认收货；
- 每天凌晨 2 点跑对账；
- 一个任务失败了，**1 秒、2 秒、4 秒** 后再试（指数退避）。

这些都要一个 **任务调度器**：任务带着「什么时候可以执行」（`run_at`）和「多重要」（`priority`）进来；worker 来拿任务执行；执行完了报告结果。

一个靠谱的调度器要处理好这几件事：

1. **延迟 + 优先级**：到点的任务里，先给优先级高的；同样优先级，先到点的先执行。用 **堆**，而不是每次扫描所有任务。
2. **租约**（lease，SQS 里叫 visibility timeout）：worker 拿走任务以后可能会崩溃，任务不能就这样丢了。所以拿走只是「租」30 秒，到期还没报告完成，任务就自动回到队列里，别的 worker 可以再拿。执行时间长的任务要定期 **心跳** 续租。
3. **令牌**：worker A 的租约过期了，任务被 worker B 拿走。这时候 A 从卡顿中醒过来，报告「我做完了」，不能被接受。每次租出都发一个新的、递增的令牌，只认当前的令牌（Day 12 的 fencing token）。
4. **退避重试和死信**：失败了等一会儿再试，等待时间指数增长，试了太多次就放进 **死信**（dead），等人来看（Day 7 的 DLQ）。

## 要求

实现 `solution.py` 里的 `TaskScheduler`。`Lease(task_id, payload, attempt, token)` 已经定义好了。

### 构造

`TaskScheduler(*, clock=time.monotonic, lease_seconds=30.0, max_attempts=3, base_backoff=1.0, max_backoff=60.0)`

- `lease_seconds <= 0`、`max_attempts < 1`、`base_backoff < 0`、`max_backoff < base_backoff`，抛 `ValueError`。
- `backoff(attempt) -> float`：第 `attempt` 次执行失败后要等多久：`min(base_backoff × 2^(attempt-1), max_backoff)`。

### 任务状态

一个任务的状态是下面之一：

- `"pending"`：等着被执行（可能还没到点，也可能已经到点了在排队）；
- `"running"`：被某个 worker 租走了；
- `"done"`、`"dead"`、`"cancelled"`：结束了，不会再变。

**时间驱动的变化**（到点、租约到期）不需要后台线程：每个公开方法开始时，先按当前 `clock()` 把该发生的变化处理掉（惰性推进）。

### 方法

- `submit(task_id, payload=None, *, run_at=None, priority=0) -> bool`：新建一个 `pending` 任务。`run_at` 为 `None` 表示现在（`clock()`）。`priority` 越大越优先。`task_id` **已经存在**（不管是什么状态）就什么都不做，返回 `False`（提交是幂等的）；否则返回 `True`。
- `poll(n=1) -> list[Lease]`：`n < 1` 抛 `ValueError`。从 **已经到点**（`run_at <= clock()`）的 `pending` 任务里，按下面的顺序取出最多 `n` 个：
  1. `priority` 大的在前；
  2. 一样的话，`run_at` 早的在前；
  3. 还一样，**进入当前这次排队** 早的在前（新提交和重新排队都算一次进入）。

  取出的任务变成 `running`，执行次数 `attempt` 加 1，发一个新令牌（整个调度器全局递增，从 1 开始），租约到 `clock() + lease_seconds`。返回 `Lease(task_id, payload, attempt, token)` 的列表。
- `ack(task_id, token) -> bool`：任务是 `running` 并且令牌是当前令牌，就变成 `done`，返回 `True`；否则（不存在、状态不对、令牌过期）返回 `False`，什么都不改。
- `fail(task_id, token, *, retry=True) -> bool`：令牌检查同 `ack`，不通过返回 `False`。通过时：
  - `retry=False`，或者 `attempt >= max_attempts`：变成 `dead`；
  - 否则重新变成 `pending`，`run_at = clock() + backoff(attempt)`，**优先级不变**。
  - 返回 `True`。
- `heartbeat(task_id, token) -> bool`：令牌检查同上。通过时把租约延长到 `clock() + lease_seconds`。
- **租约到期**：`running` 任务的租约到期时刻 `lease_until <= clock()` 时，就像在 `lease_until` 这一刻调用了 `fail(retry=True)`：次数用完就 `dead`，否则 `run_at = lease_until + backoff(attempt)`。旧令牌从此作废。
- `cancel(task_id) -> bool`：只有 `pending` 的任务能取消（变成 `cancelled`），返回 `True`；其他情况返回 `False`。
- `state(task_id) -> str`：不存在抛 `KeyError`。`attempts(task_id) -> int`：已经执行过几次。
- `next_wakeup() -> float | None`：下一次「有事发生」的时间：所有 `pending` 任务的 `run_at` 和所有 `running` 任务的 `lease_until` 里最早的那个。都没有返回 `None`。worker 可以用它决定睡多久。
- `counts() -> dict`：五种状态各有多少个任务（五个 key 都要有，没有就是 0）。

**性能**：测试会提交 3 万个任务，要求在几秒之内全部处理完。每次 `poll` 都扫描所有任务是不行的。

提示：一个 **按 `run_at` 排序的堆** 放还没到点的任务，到点了挪到一个 **按 `(-priority, run_at, 序号)` 排序的堆**；租约也用一个堆。取消、重新排队以后，堆里会留下旧的条目，不用去堆里删，弹出来的时候检查一下它是不是「过时」的就行（**惰性删除**）。

## 接口

```python
s = TaskScheduler(lease_seconds=30, max_attempts=5)
s.submit("cancel-order-123", {"order": 123}, run_at=now + 900)   # 15 分钟后
s.submit("send-sms-9", priority=10)

# worker 循环
for lease in s.poll(10):
    try:
        handle(lease.payload)
        s.ack(lease.task_id, lease.token)
    except Exception:
        s.fail(lease.task_id, lease.token)
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-21/1-task-queue
```

共 27 个测试。最后一个 `test_many_tasks_fast` 是性能测试，前面的都过了再管它。

## 进阶（可选）

- **线程安全**：多个 worker 线程同时 `poll`，同一个任务不能被两个人拿到。加一把锁就够了吗？`poll` 要是阻塞等待（没有任务就睡到 `next_wakeup()`），新提交了一个更早的任务怎么叫醒它？（`threading.Condition`）
- **定时任务**（cron）：「每天 2 点执行」。执行完一次以后自动提交下一次。服务停了 3 个小时，错过的那次要不要补？
- 时间轮（timing wheel）：Kafka 和 Netty 里管理海量定时器用的不是堆，而是时间轮。它在什么场景下比堆好？
- 持久化：把任务存到 Redis 的有序集合（`ZADD run_at`）或者 MySQL 里，多台调度器怎么同时取任务又不重复？（`SELECT ... FOR UPDATE SKIP LOCKED`）

## 面试追问（做完后自己先想想）

- 「至少执行一次」和「恰好执行一次」：租约机制下，一个任务有没有可能被执行两次？什么时候？怎么让业务能承受（幂等）？
- 租约设多长合适？太短和太长分别会怎样？
- 低优先级的任务一直被高优先级的任务插队，永远轮不到（饥饿），怎么办？（等得越久优先级越高：aging）
- 指数退避为什么还要加 **随机抖动**（jitter）？
