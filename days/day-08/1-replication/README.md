# Day 08 · 动手题：主从复制模拟（异步复制、复制延迟、故障切换）

## 背景

Day 5 的设计题里提到了「有主复制」：所有写都走 leader（主库），leader 把自己的 **复制日志** 发给 follower（从库），follower 按顺序重放。MySQL 的 binlog 复制、PostgreSQL 的流复制、Redis 主从、MongoDB 副本集、Kafka 的分区副本，都是这个模型。

它简单好用，但每个面试官都会追着问它的几个经典问题：

1. **复制延迟**：异步复制下，写完立刻去从库读，可能读不到刚写的数据。用户发了条评论，刷新一下没了。→ **读自己的写**（read-your-writes）
2. 用户刷新两次，第一次读到新数据（落在跟得紧的从库），第二次读到旧数据（落在落后的从库），像是「时光倒流」。→ **单调读**（monotonic reads）
3. **主库挂了**，把哪个从库提升为新主？异步复制下，主库上还没来得及复制出去的写 **会丢**。→ 选数据最新的那个；或者用 **半同步复制** 保证至少一个从库有最新数据。
4. 旧主库修好后回来了，它的日志里有一段「新主库从来没见过」的写。它不能直接接着跟新主库同步，否则数据就分叉了。→ 用 **任期（term / epoch）** 发现分叉，**截断** 掉分叉的那一段。（GitHub 2012 年的 MySQL 事故就和这个有关。）

今天用一个确定性的模拟把这四件事都做一遍。没有真的网络和线程：「从库拉取日志」由测试显式调用 `sync()` 来触发，所以每个时刻谁落后多少是完全可控的。

## 模型

- 集群有若干个节点，按构造时给的顺序排列，第一个是初始 leader。初始 **任期 `term = 1`**。
- 每个节点有一份 **日志**（`LogEntry` 列表）和一份由日志重放出来的 **KV 状态**。
- 日志条目：`LogEntry(term, lsn, key, value, timestamp)`。`lsn`（日志序号）从 1 开始，**等于它在日志里的位置**（第 i 条的 lsn 是 i）；`term` 是写入时 leader 的任期；`timestamp` 是 leader 写入时 `clock()` 的值。
- 一个节点已经应用的位置 `applied_lsn` 就是它日志的长度。
- 节点可以被 `set_down` / `set_up`。宕机的节点 **保留** 它的日志和状态（硬盘还在），只是不能读写、不能同步。

## 要求

实现 `solution.py` 里的 `ReplicatedStore` 和 `Session`。所有时间都通过注入的 `clock()` 获取。

### 1. 基本复制

- `ReplicatedStore(nodes, *, clock=time.monotonic)`：`nodes` 为空或有重名抛 `ValueError`。
- 属性 `leader`（当前 leader 的名字）、`term`。方法 `followers()`：除 leader 外的节点，按构造顺序。
- `write(key, value, *, sync_replicas=0) -> int`：在 leader 上追加一条日志并应用，返回 lsn。leader 宕机抛 `NodeDownError`。
- `sync(node, max_entries=None) -> int`：follower 从 leader 拉取并应用它缺的日志（最多 `max_entries` 条），返回本次应用了几条。`node` 是 leader 本身抛 `ValueError`；`node` 或 leader 宕机抛 `NodeDownError`。
- `read(node, key, default=None)`：直接读某个节点的本地状态（可能是旧的）。节点宕机抛 `NodeDownError`。
- `applied_lsn(node)`、`log(node)`（返回日志的副本，类型是 `list[LogEntry]`）。

### 2. 复制延迟

- `lag(node) -> int`：落后 leader 多少条（leader 的日志长度减去它的，最小为 0）。
- `lag_seconds(node) -> float`：已经追上返回 `0.0`；否则返回 `clock() - 它还没应用的第一条日志的 timestamp`。这就是 MySQL `Seconds_Behind_Master` 的含义：「我现在正在等的那条写，是多久以前发生的」。想一想为什么不能简单地用「条数」来衡量延迟。

### 3. 半同步复制

- `write(..., sync_replicas=k)`：写入 leader 后，**立刻** 让 **前 k 个在线的 follower**（按构造顺序）同步到最新，然后才返回。
- 在线的 follower 不足 k 个：抛 `NotEnoughReplicasError`，并且 **这次写不能落到任何节点上**（leader 也不写）。
- `k < 0` 抛 `ValueError`。

### 4. 故障切换

- `failover() -> int`：当前 leader **必须已经宕机**，否则抛 `ValueError`（计划内的主从切换不在本题范围）。
  - 在 **在线的** follower 里选 `applied_lsn` 最大的提升为新 leader；一样大就选构造顺序靠前的。没有在线的 follower 抛 `NodeDownError`。
  - `term` 加 1。新 leader 之后写入的日志用新的任期，lsn 接着它自己的日志往后编号。
  - 返回 **丢失的写** 的条数：旧 leader 日志长度减去新 leader 日志长度。
- 其他 follower 继续 `sync()` 就能跟上新 leader（它们的日志是新 leader 日志的前缀，为什么？）。

### 5. 旧 leader 回归：发现分叉并截断

旧 leader `set_up` 回来以后就是一个普通的 follower。它对新 leader 调用 `sync()` 时：

- 如果它的最后一条日志在新 leader 的日志里 **同一个 lsn 位置上的 term 不同**，或者它的日志 **比新 leader 还长**，说明分叉了：从头比较 `(term, lsn)`，找到最后一个一致的位置，把之后的日志 **全部截断**，并 **用剩下的日志重建 KV 状态**（被截掉的写对应的 key 要恢复成截断点时的值，或者消失）。
- 然后正常拉取新 leader 的日志。返回值仍然是本次 **应用** 的条数（不含截掉的条数）。

### 6. 会话一致性：`Session`

`store.session()` 返回一个会话对象，模拟一个用户的浏览器。会话记住一个 `min_lsn`（初始为 0）：

- `session.write(key, value, **kw)`：调用 `store.write`，并把 `min_lsn` 提高到返回的 lsn。
- `session.read(key, default=None)`：
  - 按构造顺序找 **第一个** 满足「在线、不是 leader、`applied_lsn >= min_lsn`」的 follower 来读；一个都没有就读 leader。
  - 读完把 `min_lsn` 提高到所读节点的 `applied_lsn`。这一步保证了 **单调读**：一旦读到过某个版本，以后就不会再读到更旧的版本。
  - 属性 `last_node`：上一次读用的是哪个节点（尽量读从库，是为了分担主库的读压力）。

## 接口

```python
t = [0.0]
s = ReplicatedStore(["db1", "db2", "db3"], clock=lambda: t[0])
s.write("x", 1)          # 1
s.read("db2", "x")       # None：还没复制过去
s.sync("db2")            # 1
s.read("db2", "x")       # 1

sess = s.session()
sess.write("bio", "hi")
sess.read("bio")         # "hi"：从库都没跟上，自动读主库
sess.last_node           # "db1"
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-08/1-replication
```

共 33 个测试。建议顺序：`-k basic` → `-k lag` → `-k semisync` → `-k failover` → `-k diverge` → `-k session`。

## 进阶（可选）

- 加一个 `switchover(new_leader)`：计划内的主从切换（升级主库机器），怎么做到 **一条写都不丢**？（先停写、等目标从库追平、再切换）
- 现实里从库不需要从头保存所有日志：给每个节点加快照，日志只保留快照之后的部分。一个落后太多的从库（需要的日志已经被删了）怎么追上？（全量复制 + 增量复制，Redis 的 `PSYNC`）
- 模拟「脑裂」：旧 leader 其实没挂，只是和其他节点网络断了，还在继续接受写。你的模型能表达这种情况吗？任期能帮上什么忙？

## 面试追问（做完后自己先想想）

- 异步复制、半同步复制、同步复制，各自的写延迟和数据安全性如何？MySQL 半同步在从库超时后会退化成异步，这意味着什么？
- 读自己的写，在 **多个设备** 上怎么保证？（手机上发的评论，电脑上马上要能看到）`min_lsn` 存在哪里？
- 从库延迟突然飙到 30 秒，可能是什么原因？（大事务、从库单线程重放、从库在跑大查询）怎么监控、怎么告警？
- 主库挂了，自动切换和人工切换各有什么风险？怎么判断主库是「真的挂了」而不是「网络抖了一下」？
- 「丢了的写」在业务上意味着什么？如果这些写已经给用户返回了「成功」，事后怎么补救？
