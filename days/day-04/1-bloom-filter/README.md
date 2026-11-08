# Day 04 · 动手题：布隆过滤器（标准版 + 计数版）

## 背景

爬虫每天要见几十亿个 URL，每个都要先问一句「这个爬过没有」。把所有 URL 放进一个 `set`：100 亿个 URL，平均 80 字节，光字符串就要 800 GB。布隆过滤器用约 **每个元素 10 bit**（1.2 字节）回答同一个问题，代价是：

- 说「**不在**」时一定不在（没有假阴性）；
- 说「**在**」时可能是误判（有假阳性），误判率可以事先算好。

对爬虫来说，误判的后果是「少爬一个页面」，完全可以接受；而它省下的是上百倍的内存。同样的结构还出现在 Cassandra / HBase / RocksDB（查 SSTable 前先问布隆过滤器，省一次磁盘读）、Chrome 的恶意网址库、Medium 的推荐去重里。

## 原理（先自己推一遍公式）

- 一个长度为 `m` 的位数组，`k` 个哈希函数。
- `add(x)`：把 `k` 个哈希位置都置 1。
- `x in bf`：`k` 个位置全是 1 才返回「可能在」，有一个是 0 就是「肯定不在」。
- 插入 `n` 个元素后，某一位仍是 0 的概率约为 `e^(-kn/m)`，于是误判率 `p ≈ (1 - e^(-kn/m))^k`。
- 给定 `n` 和目标 `p`，最优参数是：
  - `m = ceil(-n · ln(p) / (ln 2)²)`
  - `k = round(m / n · ln 2)`，至少为 1
  - 例：`n=1000, p=0.01` → `m=9586, k=7`。

**k 个哈希函数怎么来？** 不用真的找 k 个不同的哈希函数。用 **双重哈希**（Kirsch–Mitzenmacher）：从一次 `hashlib` 摘要里切出两个 64 位整数 `h1`、`h2`，第 `i` 个位置是 `(h1 + i · h2) mod m`。理论上误判率和 k 个独立哈希一样。

## 要求

实现 `solution.py` 里的两个函数和两个类。

### 0. 参数计算

- `optimal_num_bits(capacity, error_rate)`、`optimal_num_hashes(num_bits, capacity)`，公式见上。

### 1. `BloomFilter(capacity, error_rate=0.01)`

- `capacity <= 0`，或 `error_rate` 不在开区间 `(0, 1)` 里，抛 `ValueError`。
- 属性 `num_bits`、`num_hashes`、`size_in_bytes`（= `ceil(num_bits / 8)`）。
- **必须用真正的位数组**（`bytearray` 按位操作，或者一个大 `int`），测试会用 `tracemalloc` 检查：100 万容量的过滤器峰值内存要小于 3 MB。用 `list[bool]` 会是 70 多 MB。
- 元素可以是 `str` 或 `bytes`，`str` 按 UTF-8 编码后处理，所以 `"abc"` 和 `b"abc"` 是同一个元素。其他类型抛 `TypeError`。
- **哈希只能用 `hashlib`**（`md5`、`sha256`、`blake2b` 都行），不能用内置 `hash()`：它对 `str` 每个进程的种子不同，过滤器存盘后重启就全乱了。测试会在两个不同 `PYTHONHASHSEED` 的子进程里各建一个过滤器，比较结果是否一致。
- `add(item)`：插入，返回这个元素插入前是不是「肯定不在」（有至少一位从 0 变成 1）。爬虫可以用它一步完成「查 + 插」。
- `item in bf`：没有假阴性；插满 `capacity` 个元素时，实测误判率不超过 `error_rate × 1.5`。
- `approx_count()`：设置为 1 的位数是 `X`，估算插入过的不同元素数为 `-(m / k) · ln(1 - X / m)`。重复插入同一个元素不影响结果。
- `false_positive_rate()`：用当前置 1 的比例估算误判率 `(X / m) ** k`。空过滤器返回 0。
- `union(other)`：返回新的过滤器（按位或），不修改两个输入。`num_bits` 或 `num_hashes` 不同抛 `ValueError`。这就是多台爬虫机器合并各自过滤器的方法。
- `to_bytes()` / `BloomFilter.from_bytes(data)`：序列化。格式自己定，但只能在位数组之外加一个很小的头（小于 64 字节），还原出来的是独立副本。

### 2. `CountingBloomFilter(capacity, error_rate=0.01)`

标准布隆过滤器不能删除：把某一位清 0，可能会把别的元素也「删掉」，造成假阴性。计数版把每一位换成一个计数器：

- `m`、`k` 和同参数的 `BloomFilter` 一样；每个计数器是 8 位（0..255），用一个长度为 `m` 的 `bytearray`。
- `add(item)`：`k` 个计数器各加 1，**已经是 255 的不再加**（饱和）。
- `item in c`：`k` 个计数器都大于 0。
- `remove(item)`：如果 `item` 肯定不在（某个计数器是 0），**什么都不改**，返回 `False`；否则 `k` 个计数器各减 1，返回 `True`。**已经饱和到 255 的计数器不减**：溢出后不知道真实值了，减下去可能减到 0 造成假阴性。
- `count(item)`：`k` 个计数器里的最小值，是插入次数的上界估计（这就是 Day 18 Count-Min Sketch 的雏形）。
- 非 `str` / `bytes` 抛 `TypeError`。

## 接口

```python
bf = BloomFilter(capacity=1_000_000, error_rate=0.01)
bf.num_bits, bf.num_hashes      # (9585059, 7)
bf.add("https://example.com/")  # True：之前肯定没见过
"https://example.com/" in bf    # True
bf.approx_count()               # ≈ 1
blob = bf.to_bytes()            # 存盘
bf2 = BloomFilter.from_bytes(blob)

c = CountingBloomFilter(1000)
c.add("x"); c.add("x")
c.count("x")                    # 2
c.remove("x")                   # True
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-04/1-bloom-filter
```

共 49 个测试。建议顺序：先 `-k optimal`（参数公式），再 `-k "not counting"`（标准版），最后 `-k counting`（计数版）。`test_bloom_false_positive_rate_matches_target` 会做 10 万次查询，如果误判率明显超标，通常是双重哈希写错了：比如 `h2` 可能为 0（k 个位置全一样），或者 `h1`、`h2` 取自摘要里重叠的字节。想一想怎么避免。

## 进阶（可选）

- **可扩展布隆过滤器**（Scalable Bloom Filter）：不知道最终会有多少元素时，满了就新开一层容量翻倍、误判率减半的过滤器，查询时逐层查。整体误判率的上界是多少？
- 用 `numpy` 或 `int.bit_count()` 重写，比较 `approx_count()` 在 1 亿位上的耗时。
- 写个脚本画出固定 `m` 时误判率随 `k` 变化的曲线，验证最优 `k = m/n · ln 2`。
- 布谷鸟过滤器（Cuckoo Filter）也支持删除，而且比计数布隆过滤器省空间。它是怎么做到的？代价是什么？

## 面试追问（做完后自己先想想）

- 100 亿个 URL、误判率 1%，布隆过滤器要多大？误判率降到 0.1% 呢？内存怎么随 `p` 变化？
- 布隆过滤器插满以后会怎样？你怎么发现它「满了」？满了以后怎么办（重建、分层、换大的）？
- 为什么计数版每个计数器 4 位通常就够了？溢出的概率是多少？
- 爬虫用布隆过滤器判断 URL 去重，误判会导致什么？反过来，如果用它判断「这个用户名被注册过没有」，误判会导致什么？哪种场景能接受？
- 「缓存穿透」（大量请求查不存在的 key，全部打到数据库）为什么可以用布隆过滤器挡？数据库里新增或删除数据时，过滤器怎么同步？
