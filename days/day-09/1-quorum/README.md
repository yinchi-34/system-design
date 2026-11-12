# Day 09 · 动手题：Quorum 读写模拟（N/W/R、向量时钟、读修复）

## 背景

Day 8 的主从复制里，所有写都要经过 leader。leader 挂了就要选主，选主期间不能写，异步复制还会丢数据。Amazon 在设计 Dynamo（购物车）时走了另一条路：**没有 leader**。

- 每个 key 存在 **N** 个节点上（它的「偏好列表」）。
- 写：发给这 N 个节点，**W** 个确认了就算成功。
- 读：从 N 个节点里读 **R** 个，取最新的。
- 只要 `W + R > N`，读的 R 个节点和写的 W 个节点 **至少有一个重叠**，就一定能读到最新写入的值（理想情况下）。

没有 leader 就意味着 **两个客户端可以同时写同一个 key**，写到不同的节点上。这时候「哪个是最新的」就没有答案了。Dynamo 的回答是 **向量时钟**：它能精确判断两个版本是「一个是另一个的后代」，还是「互相不知道对方、并发产生的」。后一种情况下两个版本都保留（叫 **兄弟版本**，siblings），交给客户端合并（购物车取并集）。

副本之间不一致了怎么办？**读修复**：读的时候顺便发现哪个副本旧了，把新版本写回去。

Cassandra、Riak、ScyllaDB、DynamoDB 的底层都是这一套。今天实现它，Day 5 设计题里的问题就都有了手感。

## 要求

实现 `solution.py` 里的 `VectorClock` 和 `QuorumStore`。

### 1. `VectorClock(counts=None)`

一个从节点名到计数的映射，没出现的节点计数视为 0。

- 计数必须是非负整数，否则抛 `ValueError`。计数为 0 的项等同于不存在（`VectorClock({"a": 0}) == VectorClock()`）。
- **不可变**：下面的方法都返回新对象，不修改自己。
- `get(node) -> int`、`to_dict() -> dict`（不含 0 项）。
- `increment(node)`：该节点计数 +1。
- `merge(other)`：逐项取最大值。
- `descends(other) -> bool`：自己的每一项都 `>=` 对方（相等也算）。
- `compare(other) -> str`：返回 `"equal"`、`"before"`（自己更旧，对方是自己的后代）、`"after"`、`"concurrent"` 之一。
- 支持 `==` 和 `hash()`（可以放进 `set`、当 `dict` 的 key）。

### 2. `QuorumStore(nodes, n=3, w=2, r=2)`

`nodes` 有重名，或不满足 `1 <= n <= len(nodes)`、`1 <= w <= n`、`1 <= r <= n`，抛 `ValueError`。

**偏好列表**：`preference_list(key)` 返回负责这个 key 的 N 个节点，用 **rendezvous 哈希**（最高随机权重哈希）计算：

```
score(node) = sha256(f"{key}|{node}".encode("utf-8")) 的前 8 个字节，按大端解释成整数
按 score 从大到小排序（score 相同按节点名升序），取前 n 个
```

它和 Day 2 的一致性哈希解决同一个问题，但不需要环。想一想：增删一个节点时，有多少 key 的偏好列表会变？

**节点状态**：`set_down(node)` / `set_up(node)`。宕机节点保留数据，但不参与读写。

**每个副本存什么**：对每个 key，一个副本存一组 **兄弟版本** `[(value, clock), ...]`，其中任意两个的向量时钟都是 `concurrent`。副本收到一个新版本 `(value, clock)` 时：

- 如果已有某个版本的时钟 `descends` 新时钟（新版本更旧，或者完全相同），**忽略** 新版本；
- 否则删掉所有被新时钟 `descends` 的旧版本，再把新版本加进去。

`replica(node, key)` 返回某个节点上这个 key 的兄弟版本列表（用于测试检查，不管节点是否在线）。

**写：`put(key, value, context=None, *, coordinator=None) -> VectorClock`**

1. 偏好列表里 **在线** 的节点，按偏好列表顺序排好，记为 `up`。
2. 协调者：`coordinator` 为 `None` 时取 `up` 的第一个；指定的话必须在 `up` 里，否则抛 `ValueError`。`up` 为空抛 `QuorumError`。
3. 新时钟 = `(context or VectorClock()).increment(coordinator)`。`context` 是客户端上一次 `get` 拿到的上下文，表示「我是在看过这些版本之后写的」。
4. 把 `up` 重新排成「协调者在最前，其余保持原顺序」，**前 W 个节点同步写入**；剩下的在线节点 **不马上写**，而是放进一个待投递列表（模拟发出去了但还在路上的网络消息）。
5. 如果 `up` 不足 W 个：仍然把能写的都写了，然后抛 `QuorumError`。**注意这里没有回滚**：客户端看到写失败了，但数据已经在部分副本上了。这是无主复制一个很重要的坑。
6. 返回新时钟。

`deliver_pending() -> int`：投递所有待投递的写。目标节点在线就写入；不在线的 **直接丢弃**（没有 hinted handoff，见进阶）。清空列表，返回实际写入的条数。

**读：`get(key) -> (values, context)`**

1. 从 `up` 的 **前 R 个** 节点读（`up` 不足 R 个抛 `QuorumError`）。
2. 把这 R 个节点的兄弟版本放在一起 **合并**：去掉被别的版本 `descends` 的，时钟相同的只留一个。
3. **读修复**：这 R 个节点里，凡是自己的版本集合（按时钟比较）和合并结果不一样的，把它的版本替换成合并结果。属性 `read_repairs` 累计修复过多少个副本。
4. 返回 `values`（合并结果里的值，顺序不限）和 `context`（合并结果所有时钟的 `merge`）。key 不存在返回 `([], VectorClock())`。

客户端拿到多个 `values` 时，应该自己合并，然后带着 `context` 写回去，这样新版本就 `descends` 所有兄弟版本，冲突消失。

## 接口

```python
st = QuorumStore(["n1", "n2", "n3", "n4", "n5"], n=3, w=2, r=2)
st.put("cart:42", ["apple"])
values, ctx = st.get("cart:42")        # (["apple"], VectorClock({...}))

# 两个客户端基于同一个上下文并发修改
a, b = st.preference_list("cart:42")[:2]
st.put("cart:42", ["apple", "milk"], ctx, coordinator=a)
st.put("cart:42", ["apple", "egg"], ctx, coordinator=b)
st.deliver_pending()
values, ctx = st.get("cart:42")        # 两个兄弟版本
st.put("cart:42", ["apple", "milk", "egg"], ctx)   # 合并后写回，冲突消失
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-09/1-quorum
```

共 47 个测试。建议顺序：`-k clock` → `-k preference` → `-k "put or get"` → `-k sibling` → `-k "repair or quorum"`。

## 进阶（可选）

- **Sloppy quorum + hinted handoff**：偏好列表里有节点宕机时，把写临时交给偏好列表之外的下一个健康节点，并附上「这本来是给 X 的」提示；X 回来后再交还。这样写永远不会因为 W 不够而失败。代价是什么？`W + R > N` 还能保证读到最新值吗？
- **删除**：直接删掉副本上的数据，会被读修复或者别的副本「复活」。用 **墓碑**（一个特殊的值，也带向量时钟）实现 `delete(key, context)`。墓碑什么时候才能真正清掉？
- 同一个协调者、同一个 `context` 先后写两次不同的值，两个新时钟完全相等，第二次写会被忽略。Riak 用 **dotted version vectors** 解决这个问题，查一下它是怎么做的。
- 向量时钟的项会随着协调者增多而变长。Dynamo 的做法是超过阈值就删掉最老的项，这会带来什么问题？

## 面试追问（做完后自己先想想）

- N=3 时，(W=1, R=3)、(W=3, R=1)、(W=2, R=2) 各适合什么读写比例的业务？W=1、R=1 有什么用？
- `W + R > N` 真的能保证读到最新值吗？举出至少两个反例（提示：今天的测试里就有一个：部分失败的写；还有 sloppy quorum、并发写）。
- 为什么 Cassandra 默认用 **最后写入者胜（LWW）+ 时间戳**，而不是向量时钟？它放弃了什么？什么样的数据用 LWW 会出问题？
- 读修复只能修被读到的 key。从来没人读的冷数据怎么保证副本最终一致？（Day 16 的 Merkle 树反熵）
- 购物车合并取并集，删掉的商品可能「复活」。为什么？怎么办？（提示：CRDT 的 OR-Set）
