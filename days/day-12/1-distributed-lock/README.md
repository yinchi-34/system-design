# Day 12 · 动手题：带租约的分布式锁 + fencing token

## 背景

单机上加锁用 `threading.Lock` 就行。多台机器要互斥地做一件事（只让一台机器跑定时任务、同一个订单只能被一个 worker 处理、秒杀时扣库存），就需要 **分布式锁**：由一个所有人都能访问的服务（Redis、ZooKeeper、etcd）来记录「锁现在归谁」。

分布式锁最难的地方是 **持锁的人可能会「死」**：

1. 持锁的机器宕机了，永远不会释放锁。→ 锁必须带 **租约**（lease / TTL），过期自动释放。持锁方如果还活着、还没干完活，要定期 **续租**。
2. 持锁的机器 **没死，只是卡住了**（GC 停顿 30 秒、虚拟机被挂起、网络断了一会儿）。这期间租约过期，锁被另一台机器拿走。卡住的机器醒过来，**以为自己还持有锁**，接着写数据。两台机器同时在写，锁形同虚设。

第二个问题光靠锁服务是解决不了的，因为卡住的那台机器根本不知道时间过去了。Martin Kleppmann 在《How to do distributed locking》里给出的答案是 **fencing token**：

- 锁服务每发出一次锁，就给一个 **单调递增** 的令牌号（33、34、35……）。
- 被保护的资源（数据库、存储）记住它见过的最大令牌号，**拒绝** 令牌号比它小的写入。
- 卡住的机器醒来后拿着旧令牌 33 去写，而新持有者已经用 34 写过了，存储直接拒绝。

还有一个细节：客户端判断「我还持有锁」时，不能用锁服务那边的过期时间（两台机器的时钟不一样，请求在网络上也要花时间）。保守的做法是：**从发请求之前的那一刻开始算** 租约，再减去一点时钟漂移的余量。

今天实现锁服务、带 fencing 的存储、以及一个「谨慎」的客户端。

## 要求

实现 `solution.py` 里的 `LockServer`、`FencedStorage` 和 `LockClient`。所有时间都通过注入的 `clock()` 获取，不开后台线程。

### 1. `LockServer(*, clock=time.monotonic)`：锁服务

一个锁由名字标识。每个锁同一时刻最多一个持有者。`Lease(name, owner, token, expires_at)` 已经定义好。

- `acquire(name, owner, ttl) -> Lease | None`：锁空闲（没人持有，或者原来的租约已经过期）时，发一个新租约：`token` 是 **这个锁名** 的计数器加 1（第一次是 1，之后不管谁拿到都继续递增，**过期了也不回收号码**），`expires_at = now + ttl`。锁被别人（**包括自己**，不可重入）持有时返回 `None`。`ttl <= 0` 抛 `ValueError`。
- 「过期」的判定：`now >= expires_at`。
- `renew(name, owner, token, ttl) -> bool`：只有 `owner` 和 `token` 都和当前有效的租约一致时，把 `expires_at` 更新为 `now + ttl`，返回 `True`。租约已经过期的，**即使还没被别人拿走也不能续**，返回 `False`。
- `release(name, owner, token) -> bool`：只有 `owner` 和 `token` 都一致、且租约还有效时才释放，返回 `True`；否则什么都不做，返回 `False`。
  - 想一想：为什么释放时要同时核对 owner 和 token，而不是直接 `DEL lock`？（提示：Redis 上的经典 bug：A 的锁过期了，B 拿到了锁，A 执行完了把 B 的锁删了）
- `holder(name) -> Lease | None`：当前有效的租约。
- 线程安全。

### 2. `FencedStorage()`：被保护的资源

- `write(key, value, token)`：如果 `token` **小于** 它见过的最大令牌号，抛 `StaleTokenError`，**不写入**；否则写入，并把最大令牌号更新为 `token`。相同的令牌号可以写多次（同一个持有者连续写）。
- `read(key, default=None)`。
- `max_token` 属性：见过的最大令牌号，初始为 0。
- 注意：最大令牌号是整个存储共用一个（这个存储整体被一把锁保护），不是每个 key 一个。

### 3. `LockClient(server, owner, *, clock=time.monotonic, drift_factor=0.01)`：谨慎的客户端

客户端自己记录每把锁的 **本地有效期**：

```
本地有效期截止 = 发请求之前的时间 start + ttl - ttl × drift_factor
```

- `acquire(name, ttl) -> bool`：先记下 `start = clock()`，再调用 `server.acquire`。拿不到返回 `False`。拿到了，但请求花的时间太长，**拿到时已经过了本地有效期**（`clock() >= 截止`）：这把锁已经没有意义了，立刻向服务端 `release`，返回 `False`。否则记录下来，返回 `True`。
- `is_held(name) -> bool`：本地记录存在且 `clock() < 截止`。**只看本地时钟，不问服务端**。
- `token(name) -> int`：持有时返回令牌号，不持有抛 `LockNotHeldError`。
- `renew(name) -> bool`：本地已经认为不持有了，就不再去续（返回 `False`，并删除本地记录）。否则同样先记 `start`，用原来的 `ttl` 调 `server.renew`：成功则按新的 `start` 更新本地截止时间；失败则删除本地记录，返回 `False`。
- `release(name) -> bool`：没有本地记录返回 `False`；否则删除本地记录，并返回 `server.release` 的结果。
- `lock(name, ttl)`：上下文管理器。拿不到锁抛 `LockNotAcquiredError`；拿到了就 `yield` 令牌号，退出时（包括异常退出）释放。
- `drift_factor` 不在 `[0, 1)` 里抛 `ValueError`。

## 接口

```python
server = LockServer()
storage = FencedStorage()
a = LockClient(server, "worker-a")

with a.lock("order:42", ttl=10) as token:
    storage.write("order:42", "paid", token)
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-12/1-distributed-lock
```

共 28 个测试。建议顺序：`-k server` → `-k fence` → `-k client`，最后看 `-k scenario`（把三者组合起来，重现「GC 停顿导致两个持有者」的经典事故）。

## 进阶（可选）

- **Redlock**：同时向 5 个独立的 Redis 申请锁，拿到 3 个以上、并且总耗时小于租约才算成功。用 5 个 `LockServer` 实现它。然后读 Kleppmann 对 Redlock 的批评和 antirez 的回应，你站哪一边？
- **公平锁**：拿不到锁的客户端排队，锁释放时按顺序交给下一个。ZooKeeper 用临时顺序节点 + 只监听前一个节点做到这一点，为什么不让所有人都监听锁节点（惊群）？
- **读写锁**：多个读者可以同时持有，写者独占。租约和令牌号怎么设计？
- 给 `LockClient` 加一个 `tick()` 方法，模拟后台续租线程：剩余时间少于 1/3 租约时自动续租，续租失败时调用一个回调通知业务「你已经失去锁了」。业务收到回调后应该做什么？

## 面试追问（做完后自己先想想）

- Redis 用 `SET key value NX PX 30000` 加锁、用一段 Lua 脚本「比较后删除」来解锁。为什么解锁一定要用 Lua 脚本？
- Redis 主从异步复制：客户端在主库上拿到锁，主库还没复制到从库就挂了，从库被提升为新主库，另一个客户端又拿到了同一把锁。怎么办？ZooKeeper / etcd 为什么没有这个问题？
- 租约设多长合适？太短会怎样，太长会怎样？
- fencing token 要求被保护的资源配合检查令牌号。如果资源是一个第三方 API（比如调用银行转账），没法让它检查令牌号，怎么办？
- 很多场景其实不需要分布式锁：用数据库的唯一约束、条件更新（乐观锁 `WHERE version = ?`）、或者把同一个 key 的请求路由到同一个分区串行处理，就能达到同样的效果。今天的设计题「秒杀」里，你会用锁吗？
