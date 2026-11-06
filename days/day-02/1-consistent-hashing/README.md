# Day 02 · 动手题：一致性哈希（虚拟节点 + 权重 + 副本）

## 背景

昨天的追问里留了个伏笔：10 亿个 key 单机放不下，要分到多台缓存机器上。最直接的做法是 `hash(key) % N`，可一旦加一台机器（N 变成 N+1），**几乎所有 key 都会换机器**，缓存瞬间全部失效，请求全打到数据库上。

一致性哈希把节点和 key 都映射到同一个环上，key 顺时针找到的第一个节点就是它的归属。加减一个节点时，只有环上相邻那一小段的 key 需要迁移。Dynamo、Cassandra、Memcached 客户端（ketama）、Nginx 的 `hash ... consistent`、很多 RPC 框架的负载均衡都用它。

面试里考的点：环的查找怎么做到 O(log V)、虚拟节点为什么能解决负载不均、加减节点时到底哪些数据要迁移、副本怎么放。

## 要求

实现 `solution.py` 里的 `ConsistentHashRing` 类。

**环与哈希**

- 哈希函数 `hash_fn(s: str) -> int` 由构造函数注入。默认用 `default_hash`：取 `md5(s.encode("utf-8"))` 的前 8 个字节，按大端序转成整数（骨架里已经写好，直接用）。
- 节点名是字符串。一个物理节点在环上放 `vnodes × weight` 个虚拟节点（取整，见下），第 `i` 个虚拟节点的位置是 `hash_fn(f"{node}#{i}")`，`i` 从 0 开始。**这个格式不要改**，测试会用自定义哈希函数精确检查位置。
- 查找 key：计算 `h = hash_fn(key)`，在环上找 **第一个位置 >= h 的虚拟节点**，返回它所属的物理节点。如果 `h` 比所有位置都大，就绕回环的起点（取位置最小的虚拟节点）。
- 不用考虑两个虚拟节点哈希完全相同的情况，测试不会构造这种冲突。

**节点管理**

- `__init__(nodes=None, vnodes=100, hash_fn=default_hash)`：`vnodes` 必须 ≥ 1，否则抛 `ValueError`。`nodes` 是初始节点列表，每个以权重 1 加入。
- `add_node(node, weight=1.0)`：
  - `weight` 必须 > 0，否则抛 `ValueError`。
  - 虚拟节点数为 `max(1, round(vnodes * weight))`。
  - 节点已存在时抛 `ValueError`。
- `remove_node(node)`：节点不存在时抛 `KeyError`。删除后，该节点的所有虚拟节点都要从环上消失。
- `nodes`：返回当前所有物理节点组成的 `set`（返回副本，外部改它不影响环）。
- `len(ring)` 返回物理节点数，`node in ring` 判断物理节点是否存在。

**查找**

- `get_node(key)`：返回 key 归属的物理节点。环为空时抛 `LookupError`。
- `get_nodes(key, n)`：返回 key 的 **n 个副本节点**，用来做多副本存储。
  - 从 key 的位置开始顺时针走，依次收集 **不重复的物理节点**，同一物理节点的其他虚拟节点要跳过。
  - 返回列表，顺序就是顺时针遇到的顺序，所以第一个元素一定等于 `get_node(key)`。
  - `n` 大于物理节点数时，返回全部物理节点（仍按顺时针顺序）。
  - `n < 1` 抛 `ValueError`；环为空抛 `LookupError`。

**复杂度**

- `get_node` 必须是 **O(log V)**，V 是虚拟节点总数。提示：维护一个有序的位置列表，用 `bisect`。不能每次查找都线性扫一遍。
- `add_node` / `remove_node` 允许 O(V)（甚至 O(V log V)），因为它们很少发生。
- `get_nodes(key, n)` 在最坏情况下可以走完整个环，但正常情况应该很快就收集够。

**一致性（测试会重点验证）**

- 结果只取决于当前有哪些节点和权重，**与加入顺序无关**。
- 加入一个新节点后，换了归属的 key **只能** 是搬到了新节点上，不能在老节点之间互相搬。
- 删除一个节点后，只有原来属于它的 key 会换归属，其他 key 不动。

## 接口

```python
ring = ConsistentHashRing(["cache-a", "cache-b", "cache-c"], vnodes=150)
ring.get_node("user:42")          # 例如 "cache-b"
ring.get_nodes("user:42", 2)      # 例如 ["cache-b", "cache-a"]
ring.add_node("cache-d", weight=2)  # 机器配置是别人的两倍
ring.remove_node("cache-a")
len(ring)                         # 3
"cache-a" in ring                 # False
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-02/1-consistent-hashing
```

测试里有一个负载均衡测试：10 个节点、每个 200 个虚拟节点、10 万个 key 时，负载最高的节点不能超过平均值的 1.3 倍。用默认哈希、按题目规定的虚拟节点命名，就能通过。

## 进阶（可选）

- 写一个 `migration_plan(old_ring, new_ring, keys)`，返回 `{key: (from_node, to_node)}`，只包含要迁移的 key。再想想：真实系统里你手上没有完整的 key 列表，怎么只靠环上的 **哈希区间** 算出要迁移哪些数据？
- 不枚举 key，直接算出每个节点在环上占了多大比例的区间，打印出来看看虚拟节点数从 1 增加到 1000 时，负载的标准差是怎么下降的。
- 了解一下 Jump Consistent Hash 和 Rendezvous Hashing（最高随机权重），对比它们和环的优缺点。

## 面试追问（做完后自己先想想）

- 不用虚拟节点会出什么问题？虚拟节点数取多少合适，太多有什么代价？
- 加一台新机器，它接管的 key 原来分散在哪几台机器上？迁移期间读请求怎么处理（双读？先迁再切？）
- `get_nodes` 为什么要跳过同一个物理节点？如果机器分布在 3 个机房，怎么保证 3 个副本落在不同机房？
- 某个 key 特别热（比如明星的主页），一致性哈希能解决吗？不能的话怎么办？
- 为什么 Redis Cluster 没用一致性哈希，而是用固定的 16384 个槽？
