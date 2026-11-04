# Day 01 · 动手题：带 TTL 的 LRU 缓存

## 背景

LRU（Least Recently Used）是最常见的缓存淘汰策略，Redis 的 `allkeys-lru`、Memcached、数据库 buffer pool、CDN 边缘节点都在用它的变体。面试里它几乎是必考的热身题：考的是你能不能用 **哈希表 + 双向链表** 做到 O(1)，以及能不能把过期时间（TTL）这类真实需求干净地加进去。

## 要求

实现 `solution.py` 里的 `LRUCache` 类。

**容量与淘汰**

- `capacity` 必须 ≥ 1，否则抛 `ValueError`。
- 缓存满了再 `put` 一个 **新 key** 时，淘汰最久没被使用的那一个。
- `get` 命中和 `put`（新增或更新）都算一次“使用”，会把该 key 变成最新。
- `__contains__`（`key in cache`）**不算** 使用，不改变顺序。

**TTL**

- `put(key, value, ttl=None)`：`ttl` 单位是秒，可以是小数。
  - 传了 `ttl` 就用它；没传就用构造时的 `default_ttl`；两者都是 `None` 表示永不过期。
  - `ttl` 或 `default_ttl` 不是 `None` 时必须 > 0，否则抛 `ValueError`。
- 写入时刻为 `t`，则当 `clock() >= t + ttl` 时该条目视为 **已过期**。
- 对已存在的 key 再次 `put`：更新值，并按本次的 ttl 规则 **重新计算** 过期时间。
- 已过期的条目对外表现得和不存在一样：`get` 返回 `default`，`in` 返回 `False`，`delete` 返回 `False`。
- 允许惰性删除（访问时才清理），不要求后台线程。

**时间**

- 构造函数接收 `clock` 参数（默认 `time.monotonic`），所有时间判断都必须通过它取当前时间。测试会注入假时钟，所以不要直接调 `time.time()`。

**复杂度**

- `get` / `put` / `delete` / `in` 都必须是 **O(1)**。
- **不允许** 使用 `collections.OrderedDict` 或 `functools.lru_cache`，自己写双向链表。这正是面试官想看的部分。

## 接口

```python
cache = LRUCache(capacity=2, default_ttl=None)
cache.put("a", 1)
cache.put("b", 2, ttl=10)
cache.get("a")        # 1，同时 "a" 变成最新
cache.put("c", 3)     # 满了，淘汰 "b"
"b" in cache          # False
cache.delete("a")     # True
len(cache)            # 1
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-01/1-lru-cache
```

## 进阶（可选）

- 让 `__len__` 只统计未过期的条目，同时保持 O(1)（提示：想想你需要额外维护什么）。
- 满了需要淘汰时，优先淘汰已过期的条目，而不是最久未使用的。
- 线程安全版本：加锁的粒度怎么选？
- 主动过期：参考 Redis 的“定期随机抽样 + 惰性删除”策略。

## 面试追问（做完后自己先想想）

- 为什么要用双向链表而不是单向链表？哨兵（dummy）节点解决了什么问题？
- 如果缓存要存 10 亿个 key，单机放不下，你怎么把它变成分布式缓存？（这是明天一致性哈希的伏笔）
- LRU 在什么访问模式下会表现很差？LFU、LRU-K、W-TinyLFU 分别怎么解决？
- 用户发起一次全表扫描，会把热点数据全挤出缓存，怎么防？
