# Day 15 · 动手题：Raft 选主模拟

## 背景

Day 8 的主从复制里，主库挂了以后「把哪个从库提升为新主」是由 `failover()` 这个「上帝视角」的函数决定的。现实中没有上帝：每个节点只能通过收发消息知道别人的状态，网络会延迟、丢包、分区，节点会宕机又回来。在这样的条件下，怎么让一群节点 **自己** 选出一个 leader，并且保证 **任何时刻都不会有两个 leader 同时以为自己说了算**？

**Raft** 就是为了「好理解」而设计的共识算法，etcd、Consul、TiKV、CockroachDB、Kafka（KRaft）都在用它。完整的 Raft 有三部分：选主、日志复制、安全性。今天只做 **选主**，这是整个算法的骨架。

核心概念：

- **任期（term）**：一个单调递增的整数，相当于「第几届」。每一届最多选出一个 leader。任何消息都带着发送者的任期。
- **三种状态**：follower（跟随者）、candidate（候选人）、leader。
- **选举超时**：follower 在 `election_timeout` 时间内没有收到 leader 的心跳，就认为 leader 挂了，自己变成 candidate：任期 +1、给自己投一票、向所有人拉票。
- **投票规则**：每个节点在每个任期里 **最多投一票**，先到先得。拿到 **过半数** 的票（包括自己那一票）就成为 leader。
- **心跳**：leader 定期发心跳（空的 AppendEntries），告诉大家「我还活着」，压住别人的选举。
- **看到更大的任期就退位**：任何节点收到任期比自己大的消息，立刻更新任期、变回 follower。这一条保证了「旧 leader」回来后会自动让位。
- **选举限制**：只把票投给日志 **至少和自己一样新** 的候选人。这保证新 leader 一定拥有所有已提交的日志（Day 8 里「数据最新的从库当新主」的分布式版本）。

为什么选举超时要 **随机**？如果所有节点同时超时、同时拉票，票会被瓜分，谁都凑不够过半，然后又同时超时……（分票）。测试里会给不同节点设置不同的超时来模拟随机化。

## 模型

- 你只需要实现 **一个节点** `RaftNode`。它是一个纯粹的「状态机」：没有线程，没有网络，没有真的时钟。
- 测试里有一个模拟网络：调用每个节点的 `tick(now)`，把它返回的消息放进网络；网络再按测试设定的顺序、延迟、丢包规则，调用目标节点的 `receive(msg, now)`，把返回的消息继续放进网络。
- 消息类型 `Message`（已定义好）：`kind`、`src`、`dst`、`term`，以及 `last_log_index`、`last_log_term`（拉票用）、`granted`（投票结果）、`success`（心跳结果）。
- 日志只用来做选举限制：每个节点有一个 `log_terms` 列表，第 i 项是第 i+1 条日志的任期。`last_log_index = len(log_terms)`，`last_log_term = log_terms[-1]`（空日志为 0）。今天不需要复制日志。

## 要求

实现 `solution.py` 里的 `RaftNode`。

### 构造：`RaftNode(node_id, peers, *, election_timeout, heartbeat_interval=1.0, log_terms=None, now=0.0)`

- `peers` 是集群里所有节点的 id（可能包含自己，要去掉）。`election_timeout <= 0` 或 `heartbeat_interval <= 0` 抛 `ValueError`。
- 初始状态：`state = FOLLOWER`，`current_term` = 日志里最大的任期（没有日志就是 0），`voted_for = None`，`leader_id = None`。选举计时器从 `now` 开始算。
- 公开属性：`state`、`current_term`、`voted_for`、`leader_id`、`log_terms`。
- 「过半数」= 集群总节点数 `// 2 + 1`（集群总数 = peers 个数 + 1）。

### `tick(now) -> list[Message]`

- **leader**：距离上次发心跳 `>= heartbeat_interval`，就给每个 peer 发一个 `APPEND_ENTRIES`（任期为当前任期），否则返回 `[]`。
- **follower / candidate**：距离选举计时器上次重置 `>= election_timeout`，就 **发起选举**：
  - 变成 candidate，`current_term += 1`，`voted_for = 自己`，得票集合 = {自己}，`leader_id = None`，**重置选举计时器**；
  - 给每个 peer 发 `REQUEST_VOTE`，带上自己的 `last_log_index` 和 `last_log_term`；
  - 如果自己一票就已经过半（单节点集群），直接成为 leader（见下面「成为 leader」）。
  - candidate 在本轮选举超时了（分票），再次发起新一轮选举，任期再 +1。

### `receive(msg, now) -> list[Message]`

**第一条规则（对所有消息）**：如果 `msg.term > current_term`，先把 `current_term` 更新为 `msg.term`，变回 follower，`voted_for = None`，`leader_id = None`，然后再按下面处理这条消息。

- **`REQUEST_VOTE`**：同时满足下面三条才投赞成票：
  1. `msg.term == current_term`（任期比自己小的拉票一律拒绝）；
  2. `voted_for` 是 `None` 或者就是 `msg.src`（同一任期只投一票，同一个人重复来要票可以再给一次）；
  3. 候选人的日志至少和自己一样新：先比 `last_log_term`，大的更新；相同再比 `last_log_index`，大的或相等就算「至少一样新」。
  
  投赞成票时：`voted_for = msg.src`，**并且重置自己的选举计时器**（刚投完票就别急着自己去选了）。无论赞成还是反对，都回一个 `VOTE_RESPONSE`（`term` 为自己的当前任期，`granted` 为结果）。
- **`VOTE_RESPONSE`**：只有当自己还是 candidate、`msg.term == current_term`、`granted` 为真时，才记一票。票数过半就 **成为 leader**。其他情况忽略，返回 `[]`。
- **`APPEND_ENTRIES`**（心跳）：
  - `msg.term < current_term`：这是一个过时的 leader 发来的，回 `APPEND_RESPONSE(success=False)`，**不重置** 计时器。
  - 否则：如果自己是 candidate，退回 follower（同一任期里别人已经赢了）。设置 `leader_id = msg.src`，重置选举计时器，回 `APPEND_RESPONSE(success=True)`。
- **`APPEND_RESPONSE`**：今天不需要处理（第一条规则已经处理了「对方任期更大」的情况），返回 `[]`。

**成为 leader**：`state = LEADER`，`leader_id = 自己`，并且 **立刻** 给每个 peer 发一轮心跳（这一轮也算作「上次发心跳的时间」）。

所有回复消息的 `src` 是自己，`dst` 是原消息的 `src`。

## 接口

```python
a = RaftNode("a", ["a", "b", "c"], election_timeout=3)
a.tick(3.0)      # [Message(REQUEST_VOTE, "a", "b", term=1, ...), Message(REQUEST_VOTE, "a", "c", term=1, ...)]
a.state          # "candidate"
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-15/1-raft-election
```

共 31 个测试。建议顺序：`-k basic` → `-k vote` → `-k election` → `-k heartbeat` → `-k partition` → `-k safety`（最后一个是随机化的网络：延迟、乱序、丢包，反复检查「同一任期最多一个 leader」）。

## 进阶（可选）

- 加上 **日志复制**：leader 的 `propose(cmd)` 追加日志，用 AppendEntries 发给 follower，带上 `prev_log_index` 和 `prev_log_term`，follower 不匹配就拒绝，leader 往回退重试。过半复制成功的日志才算「已提交」。
- **Pre-Vote**：一个被网络隔离的节点会不停超时、不停把任期 +1。它回到集群时，带着一个巨大的任期，会把正常工作的 leader 赶下台。Pre-Vote 是怎么解决这个问题的？
- **Leader 租约读**：leader 怎么确认自己「现在」还是 leader，从而安全地直接返回读请求，而不必每次读都走一轮多数派确认？

## 面试追问（做完后自己先想想）

- 为什么是「过半数」？5 个节点的集群最多能容忍几个节点挂掉？4 个节点呢？为什么集群一般用奇数个节点？
- 网络分区：5 个节点分成 2 + 3 两边，旧 leader 在 2 那一边。两边各会发生什么？分区恢复后呢？
- 选举超时一般设成 150 到 300 ms 的随机值，心跳间隔 50 ms 左右。如果心跳间隔大于选举超时会怎样？
- Raft 和 Day 9 的 Quorum（W + R > N）都用了「多数派」，它们的目的有什么不同？
- 今天的设计题「配置中心」为什么几乎都基于 Raft（etcd）或 ZAB（ZooKeeper）？
