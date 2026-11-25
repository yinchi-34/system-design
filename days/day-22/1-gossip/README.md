# Day 22 · 动手题：Gossip 成员协议（心跳计数器 + 故障检测 + 集群模拟）

## 背景

一个有几百上千台机器的集群（Cassandra、Redis Cluster、Consul、打车平台里成千上万的位置服务节点），每台机器都需要知道：**现在集群里有哪些成员？谁挂了？**

最简单的办法是找一个中心节点，所有人都向它发心跳。但中心节点本身会成为瓶颈和单点。另一个办法是每台机器给其他所有机器发心跳，`n` 台机器每轮就是 `n²` 条消息，1000 台机器就是 100 万条，太多了。

**Gossip**（流言）协议的思路是模仿谣言的传播：

- 每台机器维护一张 **成员表**：每个成员的 **心跳计数器**，以及「我上次看到它的计数器变大是什么时候」。
- 每一轮，每台机器把自己的计数器加 1，然后 **随机挑几个**（`fanout`，比如 2 个）已知的成员，把整张表发给它们。
- 收到别人的表，逐项比较：谁的计数器比我知道的大，就更新，并把「最后看到」的时间记为现在。
- 某个成员的计数器 **很久没有变大**（超过 `fail_timeout`），就认为它挂了。

每条消息只发给几个人，但信息会像病毒一样指数扩散：大约 `O(log n)` 轮就能传遍整个集群。总消息量是每轮 `n × fanout`，而不是 `n²`。

还有一个细节：判定死亡以后不能立刻把它从表里删掉。别的节点可能还没发现它死了，还在传它的旧心跳；如果马上删了，再收到旧心跳就会把它当成新成员「复活」。所以要先标记为死亡，再保留一段时间（`cleanup_timeout`）才真正删除。

## 要求

实现 `solution.py` 里的 `GossipNode` 和 `GossipCluster`。

### 1. `GossipNode(node_id, *, clock, fail_timeout, cleanup_timeout, rng=None)`

- `fail_timeout <= 0` 或 `cleanup_timeout < 0` 抛 `ValueError`。`rng` 是 `random.Random`，`None` 时自己新建一个。
- 成员表里每一项有三个信息：心跳计数器、**最后更新时间**（本地 `clock()`）、状态（`"alive"` 或 `"dead"`）。一开始只有自己：心跳 0，最后更新时间是 `clock()`，`"alive"`。
- `heartbeat` 属性：自己的心跳计数器。
- `tick()`：
  1. 自己的心跳加 1，最后更新时间设为现在。
  2. 检查其他每个成员：`"alive"` 的，如果 `现在 - 最后更新时间 >= fail_timeout`，标记为 `"dead"`；`"dead"` 的，如果 `现在 - 最后更新时间 >= fail_timeout + cleanup_timeout`，从表里删除。（同一次 `tick` 里可以先变成 dead 再被删掉。）
- `digest() -> dict`：所有 `"alive"` 成员（包括自己）的 `{id: 心跳}`。死掉的成员 **不** 传播。
- `merge(digest) -> int`：逐项处理，返回这次新增或更新了几个成员：
  - 是自己的 id：忽略（别人对我的看法不能改我自己的心跳）。
  - 表里没有：新增，状态 `"alive"`，最后更新时间是现在。
  - 表里有，并且收到的心跳 **严格大于** 表里的：更新心跳，最后更新时间设为现在，状态设为 `"alive"`（包括把 `"dead"` 的救活：更大的心跳说明它确实还活着）。
  - 否则什么都不做。
- `status(node_id)`：`"alive"`、`"dead"`，或者不在表里时返回 `None`。
- `alive_members()`、`dead_members()`：对应状态的成员 id，升序。`alive_members` 包括自己。
- `pick_peers(k) -> list`：从 **除自己以外** 的 `"alive"` 成员里随机挑 `min(k, 个数)` 个。为了结果可复现，必须先把候选 **排好序**，再调用 **一次** `rng.sample(候选, 个数)`。

### 2. `GossipCluster(n, *, fanout=2, fail_timeout=10, cleanup_timeout=20, drop_rate=0.0, seed=0)`

一个按轮推进的集群模拟器。

- `n < 1`、`fanout < 1`、`drop_rate` 不在 `[0, 1)` 里，抛 `ValueError`。
- 公开属性：
  - `time`：当前是第几轮，从 0 开始。所有节点的 `clock` 都返回这个值。
  - `ids`：`["n0", "n1", ..., f"n{n-1}"]`。
  - `nodes`：`{id: GossipNode}`。每个节点的 `rng` 是 `random.Random(f"{seed}:{id}")`；集群自己另外有一个 `random.Random(seed)`，专门用来决定丢包。
  - `down`：挂掉的节点 id 的集合。
  - `messages`：一共发出过多少条消息。
- 初始时，`n0` 是种子节点：除了 `n0` 以外的每个节点都 `merge({"n0": 0})`。`n0` 只认识自己。
- `step()`：
  1. `time += 1`。
  2. 所有没挂的节点按 `ids` 顺序 `tick()`。
  3. 所有没挂的节点按 `ids` 顺序：取自己的 `digest()`，`pick_peers(fanout)` 挑出目标，对每个目标：`messages += 1`；如果 `reachable(发送者, 目标)`，并且集群的 `rng.random() >= drop_rate`，目标就 `merge` 这份 digest。（不可达的目标不调用 `rng.random()`。）
- `kill(node_id)`：节点挂掉，从此不 `tick`、不发、不收。
- `partition(*groups)`：把节点分成几组，只有同组的节点之间能通信。`heal()`：取消分区。
- `reachable(a, b)`：`b` 没挂，并且 `a`、`b` 在同一组（没有分区时都在同一组）。
- `converged() -> bool`：每个没挂的节点，它的 `alive_members()` 都 **正好等于**「没挂的、和它在同一组的所有节点」（升序）。
- `run_until(pred, max_rounds) -> int | None`：一轮一轮地 `step()`，每轮之后检查 `pred()`，第一次为真时返回已经跑的轮数；跑满 `max_rounds` 轮还不为真，返回 `None`。

做之前，先自己想明白：为什么 gossip 只需要 `O(log n)` 轮就能传遍？为什么心跳要用「计数器」，而不是直接传「我上次心跳的时间戳」？

## 接口

```python
cl = GossipCluster(64, fanout=2, fail_timeout=10)
cl.run_until(cl.converged, 100)     # 大约 log2(64) 的几倍轮
cl.kill("n5")
cl.run_until(cl.converged, 100)     # 超时后，大家都知道 n5 挂了

n = cl.nodes["n0"]
n.alive_members()                   # ["n0", "n1", ...]
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-22/1-gossip
```

共 22 个测试。建议顺序：`-k node` → `-k cluster`。

## 进阶（可选）

- 节点重启以后心跳从 0 开始，别人表里它的心跳还是 500，新的心跳永远「不够大」。怎么办？（加一个 **代数 / incarnation**：重启时加 1，比较时先比代数再比心跳）
- 分区恢复以后，两边已经互相判死了，`pick_peers` 只挑活着的成员，永远不会再联系。真实系统怎么解决？（定期也给种子节点、或者随机一个死节点发消息）
- **SWIM 协议**（Consul、Memberlist 用的）：不靠心跳超时，而是主动 ping 一个随机成员；不回复的话，请其他 k 个成员帮忙间接 ping；还不通才标记为「疑似」（suspect），给它一个机会反驳。它解决了心跳计数器的什么问题？
- 现在每条消息都发整张成员表，1000 个成员的表有多大？只发「最近变化过的」成员可以吗？

## 面试追问（做完后自己先想想）

- `fail_timeout` 设多长合适？太短会怎样（网络抖一下就误判），太长会怎样？它和 `fanout`、集群大小有什么关系？
- Gossip 是 **最终一致** 的：某一时刻，不同节点看到的成员列表可能不一样。哪些场景能接受、哪些不能？（比如选主就不能只靠 gossip，Day 15 的 Raft）
- Cassandra 用 gossip 传播成员和负载信息，用一致性哈希（Day 3）决定数据放在哪里。两者怎么配合？
- 为什么 gossip 对网络分区、消息丢失、节点频繁上下线都很「耐操」？代价是什么？
