# Day 20 · 动手题：Saga 编排器（顺序执行、失败补偿、崩溃恢复）

## 背景

订一间酒店，后台至少要做三件事：

1. 库存服务：锁定一间房；
2. 支付服务：扣款；
3. 通知服务：发确认短信和邮件。

这三件事在三个不同的服务、三个不同的数据库里。单机数据库的事务（`BEGIN ... COMMIT`）管不到别的数据库。两阶段提交（2PC）理论上可以，但它要求所有参与者在第二阶段之前一直锁着资源，任何一方慢了或者挂了，所有人都得等，第三方支付接口也根本不支持。

**Saga** 是另一种思路：放弃「要么全做、要么全不做」的原子性，改成：

- 每一步都是一个 **本地事务**，做完立刻提交；
- 每一步配一个 **补偿操作**（锁房 ↔ 释放房间，扣款 ↔ 退款）；
- 某一步失败了，就把 **前面已经成功的步骤，倒序补偿一遍**。

最终结果要么是「全部成功」，要么是「全部撤销」，中间状态对外是可见的（「房间被锁了几秒又放出来」），这叫 **最终一致**。

**编排器**（orchestrator）是负责按顺序调用每一步、出错时调用补偿的那个中心协调者。它自己也可能在执行到一半时崩溃，所以每做完一步都要写一条 **日志**，重启后读日志继续。这和 Day 5 的 WAL 是同一个思路。

## 要求

实现 `solution.py` 里的 `SagaLog` 和 `SagaOrchestrator`。`TransientError`、`Step`、`SagaResult` 已经定义好了。

- `Step(name, action, compensation=None, retries=0)`：`action(ctx)` 执行这一步并返回结果；`compensation(ctx)` 撤销这一步，`None` 表示这一步不需要撤销（比如只读查询）。
- `ctx` 是一个 `dict`，所有步骤共享。每一步成功后，编排器把它的返回值存到 `ctx[step.name]`，后面的步骤和补偿都能读到（比如退款需要知道扣款的金额）。

### 1. `SagaLog`

只追加的事件日志，按 `saga_id` 分开存。

- `append(saga_id, event)`：`event` 存成 `tuple`（传进来的是列表也要转成元组）。
- `events(saga_id) -> list[tuple]`：按追加顺序返回 **副本**，没有就返回空列表。
- `saga_id in log`：这个 saga 是否有过任何事件。

### 2. `SagaOrchestrator(log, *, compensation_retries=3)`

`compensation_retries < 0` 抛 `ValueError`。

日志里只有这几种事件（测试会逐条检查）：

| 事件 | 含义 |
| --- | --- |
| `("started",)` | saga 开始 |
| `("step_succeeded", name, result)` | 某一步成功，`result` 是 `action` 的返回值 |
| `("step_failed", name, repr(error))` | 某一步最终失败，开始补偿 |
| `("compensated", name)` | 某一步已经撤销（`compensation` 为 `None` 的也要记这一条） |
| `("compensation_failed", name)` | 某一步的补偿重试完了还是失败 |
| `("finished", status)` | 结束，`status` 是 `"succeeded"` / `"compensated"` / `"stuck"` |

#### `run(saga_id, steps, ctx=None) -> SagaResult`

- 检查参数（**在写任何日志之前**）：`steps` 为空、步骤名有重复、某一步 `retries < 0`，抛 `ValueError`；`saga_id` 已经在日志里了，也抛 `ValueError`（同一个 saga 不能跑两次）。`ctx` 是 `None` 就用一个新的空字典。
- 写 `("started",)`，然后按顺序执行每一步：
  - 调用 `action(ctx)`。抛出 `TransientError` 时立刻重试，**最多重试 `step.retries` 次**（也就是最多调用 `retries + 1` 次）；抛出其他 `Exception`，不重试。
  - 成功：`ctx[name] = 结果`，写 `("step_succeeded", name, 结果)`。
  - 最终失败：写 `("step_failed", name, repr(异常))`，进入补偿。
  - **只捕获 `Exception`**。`BaseException`（比如测试里用来模拟进程被杀掉的 `Crash`）必须原样抛出去，日志就停在那里。
- 全部成功：写 `("finished", "succeeded")`，返回 `SagaResult("succeeded", None, None)`。
- **补偿**：把 **已经成功的** 步骤倒序处理（失败的那一步本身不补偿，我们假设一个本地事务失败了就是什么都没发生）：
  - `compensation` 是 `None`：直接写 `("compensated", name)`。
  - 否则调用 `compensation(ctx)`。遇到任何 `Exception` 都重试，最多调用 `compensation_retries + 1` 次。成功写 `("compensated", name)`。
  - 次数用完还失败：写 `("compensation_failed", name)` 和 `("finished", "stuck")`，**停止**（不再补偿更前面的步骤），返回 `SagaResult("stuck", 失败的步骤名, 原始异常)`。这时候需要人工介入。
  - 全部补偿完：写 `("finished", "compensated")`，返回 `SagaResult("compensated", 失败的步骤名, 原始异常)`。

#### `recover(saga_id, steps, ctx=None) -> SagaResult`

编排器崩溃重启后调用。参数检查同 `run`（但 `saga_id` 必须 **已经** 在日志里，否则抛 `KeyError`）。

- 读日志。每条 `step_succeeded` 都把结果恢复到 `ctx[name]`。
- 已经有 `finished`：什么都不调用，返回 `SagaResult(status, 失败的步骤名或 None, None)`。
- 有 `step_failed`：继续补偿。已经记了 `compensated` 的步骤跳过，其余的按上面的规则倒序补偿。返回结果里 `error` 是 `None`（原始异常对象已经随进程丢了）。
- 否则：继续往前执行。已经记了 `step_succeeded` 的步骤跳过，从第一个没有记录的步骤开始，规则和 `run` 一样。

注意：如果崩溃发生在「某一步的 `action` 已经执行成功、但日志还没写」的时候，恢复后这一步会 **再执行一次**。测试里专门演示了这个后果。

#### `status(saga_id) -> str`

有 `finished` 就返回它的 `status`；有 `step_failed` 但还没结束，返回 `"compensating"`；否则返回 `"running"`。不存在抛 `KeyError`。

做之前，先自己想明白：为什么补偿要 **倒序**？为什么补偿失败要停下来，而不是跳过它继续补偿前面的步骤？

## 接口

```python
steps = [
    Step("reserve", inventory.reserve, inventory.release),
    Step("charge",  payment.charge,    payment.refund, retries=2),
    Step("notify",  notifier.send),
]
o = SagaOrchestrator(SagaLog())
r = o.run("booking-123", steps, {"room_type": "大床房", "price": 300})
r.status          # "succeeded" / "compensated" / "stuck"

# 进程崩溃重启后：
o.recover("booking-123", steps, {"room_type": "大床房", "price": 300})
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-20/1-saga
```

共 21 个测试。建议顺序：`-k log` → `-k "happy or invalid or duplicate or status or ctx"` → `-k "fail or compensat or transient or crash_is"` → `-k recover`。

## 进阶（可选）

- 给每一步的 `action` 和 `compensation` 传一个 **幂等键**（`f"{saga_id}:{step.name}"`），让测试里「重复执行」的问题消失。下游服务要怎么配合？（Day 11 支付的幂等）
- 「补偿」不一定能完全撤销：短信已经发出去了收不回来。这样的步骤应该放在 saga 的什么位置？（提示：把不可撤销的步骤放到最后，叫作 pivot / 关键点）
- 现在是 **编排**（orchestration）：一个中心协调者调用所有人。另一种是 **协同**（choreography）：每个服务做完自己的事就发一个事件，下一个服务订阅这个事件。两种各有什么优缺点？
- 某一步要等外部回调（支付渠道异步通知结果，可能要几分钟），编排器不能一直阻塞等着。怎么把 saga 改成「状态机 + 事件驱动」？

## 面试追问（做完后自己先想想）

- Saga 不保证隔离性：用户 A 的订单扣了款、还没发通知，这时候用户 B 看到的库存是什么？会出现什么异常（脏读、丢失更新）？怎么缓解（语义锁：先标记为「待确认」）？
- 2PC 和 Saga 分别适合什么场景？为什么微服务里几乎都用 Saga（或者 TCC）？
- TCC（Try-Confirm-Cancel）和 Saga 有什么不同？「Try 先冻结资源」比「直接做、失败再补偿」好在哪里？
- 补偿也失败了（`stuck`），系统应该怎么做？人工处理的工单里需要哪些信息？
