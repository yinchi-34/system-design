# Day 05 · 动手题：带 WAL 的单机 KV 存储（崩溃恢复）

## 背景

内存里的 `dict` 最快，但进程一挂、机器一断电就全没了。几乎所有数据库都用同一招解决这个问题：**预写日志（Write-Ahead Log，WAL）**。

- 每次写之前，先把「我要做什么」追加到一个只追加（append-only）的日志文件末尾，并且确保它真的落到磁盘上（`fsync`），然后再改内存，再告诉客户端「成功」。
- 进程重启时，从头把日志重放一遍，内存状态就回来了。
- 追加写是顺序 IO，比随机写快得多。这就是 PostgreSQL 的 WAL、MySQL 的 redo log、Redis 的 AOF、RocksDB / LevelDB / Cassandra 的 commit log、Kafka 的分区日志、Raft 的日志。

但是光有日志还不够：

1. **断电时最后一条记录可能只写了一半**（torn write）。重启时必须能识别出来，并且丢掉它，而不是读出一条乱码，或者直接崩溃。
2. **日志会无限增长**。同一个 key 改了 100 万次，日志里就有 100 万条，重启要重放 100 万条。所以要定期做 **快照 + 截断日志**（compaction / checkpoint）。而做快照的过程中也可能断电。

今天把这三件事都做对。

## 文件格式（必须按这个来，测试会直接读写字节）

数据目录下只有这几个文件：

| 文件 | 作用 |
|------|------|
| `wal.log` | 预写日志，只追加 |
| `snapshot.dat` | 最近一次快照，格式和 WAL 一样，只包含 PUT 记录 |
| `snapshot.dat.tmp` | 写快照时的临时文件，正常情况下不存在 |

每条记录的二进制格式（整数都是 **大端**）：

```
+-----------+--------+------------+------------+---------+-----------+
| crc32 (4) | op (1) | key_len(4) | val_len(4) | key ... | value ... |
+-----------+--------+------------+------------+---------+-----------+
             \______________ crc32 覆盖的范围 ___________________/
```

- `op`：`1` 表示 PUT，`2` 表示 DELETE。DELETE 的 `val_len` 为 0。
- `crc32` 用 `zlib.crc32` 计算，覆盖 `op` 开始一直到记录末尾的所有字节。
- `key` 是 UTF-8 编码后的字节。
- 提示：`struct.pack(">IBII", ...)`。

## 要求

实现 `solution.py` 里的 `encode_record`、`decode_records` 和 `KVStore`。

### 1. `encode_record(op, key, value) -> bytes`

按上面的格式编码一条记录。`op` 不是 1 或 2 时抛 `ValueError`。

### 2. `decode_records(data) -> (records, valid_length)`

从字节串开头依次解码，返回 `[(op, key, value), ...]`（`key`、`value` 都是 `bytes`），以及「最后一条完好记录的结尾位置」。遇到下面任何一种情况就 **停下**，后面的字节全部不要：

- 剩下的字节不够一个 13 字节的头（写了一半的头）；
- 头是完整的，但剩下的字节不够 `key_len + val_len`（写了一半的正文）；
- CRC 对不上（比特翻转，或者写了一半恰好长度够）；
- `op` 不是 1 或 2。

想一想：为什么遇到一条坏记录就要停下，而不是跳过它继续读后面的？

### 3. `KVStore(directory, *, sync=True, compact_threshold=None)`

- 目录不存在就创建。打开时 **恢复**：先加载 `snapshot.dat`（如果有），再按顺序重放 `wal.log`。如果有 `snapshot.dat.tmp`，说明上次写快照写到一半就挂了，直接删掉、忽略它。
- 恢复时如果 `wal.log` 末尾有坏掉的字节，要把文件 **截断** 到 `valid_length`。不截断的话，新记录会追加在垃圾后面，下次恢复时就永远读不到了。
- 恢复完成后提供两个只读属性：
  - `recovered_records`：从 `wal.log` 重放了多少条记录（不含快照里的）；
  - `discarded_bytes`：从 `wal.log` 末尾截掉了多少字节。
- `put(key, value)`：`key` 是 `str`，`value` 是 `bytes`，类型不对抛 `TypeError`。**先写 WAL，再改内存**。
- `get(key, default=None)`、`delete(key)`（key 存在返回 `True` 并写一条 DELETE 记录；不存在返回 `False`，**不写日志**）、`key in store`、`len(store)`、`keys()`（返回排好序的列表）。
- **持久性**：`put` / `delete` 返回时，记录必须已经交给操作系统（`flush`）；`sync=True` 时还要 `os.fsync`。测试会在子进程里写完后直接 `os._exit(0)`（不跑任何清理代码、不关文件），然后重新打开检查数据还在。
  - 调用 fsync 时请写成 `os.fsync(...)`（测试会替换 `os.fsync` 来数调用次数）。
- `compact()`：把当前全部数据写成快照，然后清空 WAL。必须 **崩溃安全**：
  1. 把所有 PUT 记录写到 `snapshot.dat.tmp`，`flush` + `fsync`；
  2. 用 `os.replace` 把它原子地换成 `snapshot.dat`；
  3. 最后才把 `wal.log` 截断为 0。
  
  任何一步之间断电，重启后数据都必须完整。尤其想清楚：如果第 2 步完成、第 3 步没做就断电，重启时会「快照 + 旧日志全部重放一遍」，结果为什么还是对的？
- `compact_threshold`：不为 `None` 时，每次写完如果 `wal.log` 的大小 **大于等于** 这个字节数，就自动 `compact()`。
- `close()`：关闭文件。关闭后再调用 `put` / `get` / `delete` 抛 `ValueError`。支持 `with KVStore(path) as db:`。

## 接口

```python
db = KVStore("/tmp/mydb")
db.put("user:1", b"alice")
db.get("user:1")          # b"alice"
db.delete("user:1")       # True
db.close()

db = KVStore("/tmp/mydb") # 重放 WAL
db.recovered_records      # 2
db.discarded_bytes        # 0
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-05/1-wal-kv-store
```

共 37 个测试。建议顺序：先 `-k record`（编解码），再 `-k "not compact"`（读写 + 恢复），最后 `-k compact`（快照）。

## 进阶（可选）

- **组提交（group commit）**：`fsync` 一次大约 1–10 ms，每次写都 fsync，单线程最多几百 QPS。让多个并发写线程攒一批、共用一次 fsync。吞吐能提高多少？延迟变成什么样？
- 把 WAL 切成多个固定大小的段文件（`wal-000001.log`……），快照完成后直接删除旧段，而不是截断。为什么 Kafka 和 RocksDB 都这么做？
- 快照时不阻塞写：先切换到新的 WAL 段，再在后台把旧状态写成快照。怎么拿到一个「一致的」旧状态？（写时复制、MVCC）
- 再往前一步就是 **LSM 树**：内存表（memtable）满了刷成有序的 SSTable 文件，读的时候先查内存表再查 SSTable（Day 4 的布隆过滤器在这里省磁盘读），后台合并 SSTable。试着画一下它的读写路径。

## 面试追问（做完后自己先想想）

- `write()` 返回了、`flush()` 返回了、`fsync()` 返回了，这三个时刻数据分别在哪里？哪个时刻断电会丢数据？
- `sync=False`（每秒 fsync 一次，Redis `appendfsync everysec` 就是这么做的）最多丢多少数据？什么业务能接受？
- 为什么用 CRC 而不是只靠长度字段判断记录是否完整？CRC32 能保证检测出所有错误吗？
- 只把文件内容 fsync 了，新建的文件在断电后可能整个消失。为什么？（提示：目录本身也要 fsync）
- 单机 KV 怎么变成分布式 KV？今天的 WAL 在今天的设计题里扮演什么角色？
