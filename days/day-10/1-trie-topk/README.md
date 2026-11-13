# Day 10 · 动手题：Trie + Top-K（搜索联想的核心数据结构）

## 背景

在搜索框里打下 `ne`，下面马上弹出「netflix」「news」「new york weather」……这就是搜索联想（autocomplete / typeahead）。每敲一个字母就发一次请求，它必须在几十毫秒内返回，所以绝不能每次都去扫描几十亿条历史搜索词。

核心数据结构是 **字典树（Trie）**：每个节点代表一个前缀，从根走到某个节点的路径就是这个前缀。找所有以 `ne` 开头的词，只要走两步就到了。

但是光走到节点还不够：`n` 这个节点下面可能挂着几百万个词，要从里面挑出搜索次数最多的 5 个，遍历整棵子树还是太慢。工业界的做法是 **在每个节点上缓存它子树里的 Top-K**：

- 查询：走到前缀节点，直接返回缓存，`O(前缀长度)`。
- 代价：每次某个词的次数变化，要更新 **从根到这个词的整条路径上** 每个节点的缓存。写变慢了，内存也多了。

这是一个典型的「用写换读」的取舍，搜索联想读远多于写，所以划算。

另外，在离线统计热词时（比如从一天的搜索日志里求出前 1000 个热词），数据可能有几十亿条，不能全部读进内存再排序。这时候用 **大小为 K 的最小堆**：内存只占 `O(K)`，时间 `O(n log K)`。

## 要求

实现 `solution.py` 里的 `normalize_query`、`normalize_prefix`、`AutocompleteTrie` 和 `streaming_top_k`。

### 0. 规范化

- `normalize_query(q)`：转小写，去掉首尾空白，内部连续的空白（空格、Tab、换行）合并成一个空格。结果为空抛 `ValueError`。不是 `str` 抛 `TypeError`。
  - `"  New   York\tWeather "` → `"new york weather"`
- `normalize_prefix(p)`：转小写，去掉 **开头** 的空白，内部连续空白合并成一个空格，**末尾的空白保留为一个空格**（用户打了 `"new "` 想看 `new` 后面跟另一个词的结果）。可以为空字符串。不是 `str` 抛 `TypeError`。
  - `"  New  "` → `"new "`

### 1. `AutocompleteTrie(k=5)`

- `k < 1` 抛 `ValueError`。每个节点缓存它子树里的 Top-K。
- **排序规则**（所有地方都一样）：按次数 **从大到小**，次数相同按字符串 **字典序从小到大**。
- `add(query, count=1)`：先规范化，再把这个词的次数加上 `count`。`count` 必须是 `>= 1` 的整数，否则抛 `ValueError`。然后更新路径上每个节点的 Top-K 缓存。
- `suggest(prefix, limit=None) -> list[str]`：规范化前缀，返回 Top-K 里的前 `limit` 个词（`None` 表示 K 个）。前缀不存在返回 `[]`。`limit` 不在 `1..k` 之间抛 `ValueError`（缓存里只有 K 个，没法给你更多）。空前缀返回全局 Top-K。
  - **必须直接读节点缓存**。测试会在一个 10 万个词都以同一个字母开头的 Trie 上调用几千次 `suggest`，遍历子树会超时。
- `remove(query) -> bool`：把这个词彻底删掉（次数归零），返回 `True`；不存在返回 `False`。删除后路径上的缓存必须仍然正确：如果被删的词在某个节点的 Top-K 里，这个节点就要从子树里 **重新找出** 新的 Top-K（删除很少发生，这里允许遍历子树）。
  - 想一想：为什么「次数增加」只需要局部更新缓存，而「次数减少 / 删除」却需要重新扫描子树？
- `frequency(query) -> int`：次数，不存在返回 0。
- `len(trie)`：当前次数大于 0 的不同词的个数。`query in trie`：次数大于 0。

### 2. `streaming_top_k(pairs, k) -> list[tuple[str, int]]`

- `pairs` 是一个 **可迭代对象**（可能是生成器），每个元素是 `(item, count)`，`item` 不重复。
- 返回次数最大的 `k` 个 `(item, count)`，按上面的排序规则排好。不足 `k` 个就全部返回。`k < 1` 抛 `ValueError`。
- **只能遍历一次，只能用 O(k) 的额外内存**：不能 `list(pairs)`，不能 `sorted(pairs)`。测试会用 `tracemalloc` 喂进 100 万个元素，检查峰值内存。
- 提示：用 `heapq` 维护一个大小为 `k` 的堆，堆顶是当前保留的元素里 **最差** 的那个。难点在于：次数相同要按字符串 **从小到大** 保留，而 `heapq` 只有最小堆，字符串又没法取负数。想想怎么写一个小类，定义它的 `__lt__`。

## 接口

```python
t = AutocompleteTrie(k=3)
t.add("netflix", 50)
t.add("news", 30)
t.add("new york weather", 30)
t.add("nba", 10)
t.suggest("ne")            # ["netflix", "new york weather", "news"]
t.suggest("new ")          # ["new york weather"]
t.suggest("N", limit=1)    # ["netflix"]

streaming_top_k(iter([("a", 3), ("b", 5), ("c", 3)]), 2)   # [("b", 5), ("a", 3)]
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-10/1-trie-topk
```

共 38 个测试。建议顺序：`-k normalize` → `-k "trie and not remove and not perf"` → `-k remove` → `-k perf` → `-k stream`。

## 进阶（可选）

- 每个节点存 K 个字符串，内存会很大（每个词在路径上的每个节点都可能被存一次）。改成只存指向叶子节点的引用，能省多少？
- 实现 **压缩字典树**（Radix Tree）：只有一个孩子的节点链合并成一个节点。节点数会少多少？Top-K 缓存怎么放？
- 支持 **拼写纠错**：用户输入 `netflx`，仍然联想出 `netflix`（编辑距离 ≤ 1）。在 Trie 上怎么做才不用和每个词都算一遍编辑距离？
- 让热度随时间衰减（昨天的热词今天不一定热）：次数改成「按小时衰减的分数」，缓存还能增量维护吗？

## 面试追问（做完后自己先想想）

- 10 亿个不同的搜索词、平均 20 个字符，这棵 Trie 大约有多少个节点、要多少内存？一台机器放得下吗？放不下怎么拆？
- 为什么在线服务通常不实时更新 Trie，而是 **每隔一段时间离线重建一棵新的** 再整体替换？实时更新有什么麻烦（并发、缓存一致性）？
- 用户每敲一个字母就发一次请求，一个用户搜一个词可能发 10 个请求。在客户端和服务端各有什么办法降低请求量？
- `streaming_top_k` 的时间复杂度是多少？和全部排序相比，n = 10 亿、k = 1000 时差多少？如果数据分散在 100 台机器上，怎么求全局 Top-K？每台机器各求 Top-K 再合并，结果一定对吗？（提示：同一个词出现在多台机器上时就不对了）
