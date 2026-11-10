# Day 07 · 动手题：内存版发布/订阅消息队列（ack、重投、死信）

## 背景

服务之间直接同步调用（A 调 B，B 调 C），任何一个慢了、挂了，整条链路都跟着慢、跟着挂。消息队列把它们 **解耦**：生产者把消息扔进队列就返回，消费者按自己的节奏去取。几乎所有大系统都有它：Kafka、RabbitMQ、RocketMQ、Amazon SQS / SNS、Google Pub/Sub。

但消息队列真正难的地方不是「放进去、取出来」，而是：

- **消费者取走消息后崩溃了** 怎么办？消息不能丢。→ 消费者处理完要 **ack**；超时没 ack 的消息要 **重投**。这就是「至少一次」（at-least-once）投递。
- 有一条消息无论重试多少次都会让消费者崩溃（「毒消息」）。→ 重投到一定次数就放进 **死信队列**（DLQ），别让它永远堵着。
- 一条消息要被多个下游各自处理一遍（订单创建后，库存、积分、通知三个系统都要知道），而同一个下游有 10 台机器，每条消息只该被其中一台处理。→ **发布/订阅 + 消费者组**。

今天实现一个单进程、内存版的消息队列，语义上接近 SQS（可见性超时）+ Kafka（消费者组）。它是今天设计题「通知系统」的骨架。

## 概念

```
                       ┌── 消费者组 "inventory" ──> 消费者 1、消费者 2（竞争消费）
publish ──> topic ─────┼── 消费者组 "points"    ──> 消费者 3
                       └── 消费者组 "notify"    ──> 消费者 4、5、6
```

- **topic**：一个消息主题。
- **消费者组（group）**：订阅了 topic 的一个下游。每条消息会 **复制给每个组各一份**（扇出）；同一个组里，每条消息同一时刻只交给 **一个** 消费者（谁先 `poll` 到算谁的）。
- **可见性超时（ack_timeout）**：消息被 `poll` 走以后进入「处理中」（in-flight），对同组其他消费者不可见。在 `ack_timeout` 秒内 `ack` 就删除；超时了就重新变为可见，等着被再投一次。
- **回执（receipt）**：每 **一次投递** 生成一个新的、全局唯一的回执。`ack` / `nack` / `extend` 都用回执，而不是消息 ID。这样一个超时后才姗姗来迟的消费者，就不能把已经重投给别人的消息 ack 掉。

## 要求

实现 `solution.py` 里的 `Broker`。所有时间都通过注入的 `clock()`（单位秒）获取，测试用假时钟。**不要开后台线程或定时器**：超时和延迟都在每次调用时按当前时间 **惰性** 处理（和 Day 1、Day 3 一样）。

### 构造：`Broker(*, ack_timeout=30.0, max_deliveries=5, clock=time.monotonic)`

`ack_timeout <= 0` 或 `max_deliveries < 1` 抛 `ValueError`。

### topic 与订阅

- `create_topic(topic)`：重复创建什么都不做。
- `subscribe(topic, group)`：topic 不存在抛 `KeyError`。重复订阅什么都不做（不能清空已有的消息）。新订阅的组 **只收到订阅之后发布的消息**。
- `publish(topic, payload) -> str`：topic 不存在抛 `KeyError`。给每个已订阅的组各放一份，返回一个唯一的 `message_id`（同一条消息在各组里的 `message_id` 相同）。`payload` 可以是任意对象，原样交给消费者。

### 消费

- `poll(topic, group, max_messages=1) -> list[Message]`：
  - 返回最多 `max_messages` 条 **当前可见** 的消息，按 **发布顺序** 排（先发布的先返回，所以超时重投的老消息排在新消息前面）。没有就返回 `[]`。`max_messages < 1` 抛 `ValueError`。
  - 返回的每条消息进入 in-flight，截止时间 = 现在 + `ack_timeout`。
  - `Message` 有四个字段：`message_id`、`payload`、`delivery_count`（这是第几次投递，第一次是 1）、`receipt`（本次投递的回执）。
- `ack(topic, group, receipt) -> bool`：回执有效（是这条消息 **最近一次** 投递的回执，并且 **现在 < 截止时间**）就删除消息，返回 `True`；否则什么都不做，返回 `False`。
- `nack(topic, group, receipt, delay=0.0) -> bool`：消费者主动说「处理失败」。回执有效时，消息在 `delay` 秒后重新可见，返回 `True`；无效返回 `False`。`delay < 0` 抛 `ValueError`。
- `extend(topic, group, receipt, seconds) -> bool`：处理时间长的消费者「续期」，回执有效时把截止时间改成 现在 + `seconds`。`seconds <= 0` 抛 `ValueError`。

### 重投与死信

- 一条 in-flight 消息到了截止时间（`now >= deadline`）还没 ack，或者被 nack 了：
  - 如果它的 `delivery_count` 已经 `>= max_deliveries`，**移进这个组的死信队列**，不再投递；
  - 否则重新变为可见（nack 带 `delay` 的，要等到 `delay` 过去），下次投递时 `delivery_count + 1`，回执换新的。
- `dead_letters(topic, group) -> list[Message]`：按进入死信队列的先后顺序返回，`receipt` 为 `None`，`delivery_count` 是死之前最后一次投递的次数。
- `redrive(topic, group) -> int`：运维修好 bug 后，把死信队列里的消息全部放回可见队列，`delivery_count` 清零（下次投递是 1），返回放回去的条数。

### 其他

- `stats(topic, group) -> dict`：返回 `{"ready": 可见的条数, "in_flight": 处理中且未超时的条数, "delayed": nack 后还在等 delay 的条数, "dead": 死信条数}`。同样要先按当前时间处理超时。
- 除 `create_topic`、`subscribe`、`publish` 外，topic 不存在或组没有订阅，都抛 `KeyError`。
- 不同组之间完全独立：A 组 ack、nack、死信都不影响 B 组。
- **线程安全**：多个生产者和消费者线程同时调用，每条消息仍然只被同组的一个消费者拿到（没有超时的话）。

## 接口

```python
b = Broker(ack_timeout=10, max_deliveries=3)
b.create_topic("order.created")
b.subscribe("order.created", "notify")
mid = b.publish("order.created", {"order_id": 42})

[m] = b.poll("order.created", "notify")
m.payload, m.delivery_count     # ({"order_id": 42}, 1)
b.ack("order.created", "notify", m.receipt)   # True
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-07/1-pubsub-queue
```

共 35 个测试。建议顺序：先 `-k "basic or fanout or group"`，再 `-k "ack or nack or extend"`，最后 `-k "dead or redrive or thread"`。

## 进阶（可选）

- **按 key 保序**：`publish(topic, payload, key=...)`，同一个 key 的消息在同一个组里必须按顺序处理，前一条没 ack 之前后一条不能投出去（Kafka 用分区做到这一点）。这和「竞争消费」怎么兼容？一条消息卡住会怎样？
- 给 topic 加 **保留上限**（最多 N 条或最多 T 秒），满了以后怎么办：拒绝新消息（背压）、丢掉最老的？各自适合什么场景？
- 加一个 `publish(..., dedup_id=...)`：5 分钟内同一个 `dedup_id` 只入队一次（SQS FIFO 的去重）。这能把「至少一次」变成「恰好一次」吗？为什么不能？
- 用今天的 Day 5 WAL 给它加持久化，重启后 in-flight 的消息应该怎么处理？

## 面试追问（做完后自己先想想）

- 「至少一次」、「至多一次」、「恰好一次」分别怎么实现？为什么说端到端的恰好一次只能靠 **消费者幂等** 来做？
- 可见性超时设多长合适？设太短、太长分别会出什么问题？`extend` 解决了什么？
- SQS 这种「每条消息单独 ack」和 Kafka 这种「提交一个 offset」有什么区别？Kafka 的做法下，一条毒消息会怎样？
- 消费者处理速度跟不上生产者，队列积压到 1 亿条。你怎么发现？怎么处理？
- 为什么死信不直接删掉，而是要存起来、还要支持 `redrive`？
