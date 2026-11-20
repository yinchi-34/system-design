# Day 17 · 动手题：分块上传 + 断点续传 + 秒传

## 背景

在手机上传一个 2 GB 的视频，传到 90% 时进了电梯，网断了。如果只能从头再来，用户会崩溃。

大文件上传几乎都用同一套做法（YouTube、抖音、阿里云 OSS 和 AWS S3 的 Multipart Upload、tus 协议、网盘客户端都是）：

1. **创建上传会话**：先告诉服务端「我要传一个多大的文件、它的整体哈希是多少」，拿到一个 `upload_id`。
2. **分块上传**：把文件切成固定大小的块（比如 5 MB），一块一块地传，每块带上自己的校验和。某一块失败了只重传这一块。
3. **断点续传**：断网、App 被杀掉、换了网络，回来以后问服务端「这个 `upload_id` 你还缺哪几块」，只补传缺的。
4. **合并**：所有块都到齐后，服务端拼成完整文件，再校验一次整体哈希。
5. **秒传**：上传之前先问「这个哈希的文件你已经有了吗」，有了就直接返回，一个字节都不用传（Day 16 云盘里的去重）。

这一套里每一步都有容易犯错的地方：块的大小校验、重复上传同一块（网络重试）是不是幂等、会话放了三天没人管要不要清理、整体哈希对不上怎么办。今天把服务端和客户端都写出来。

## 要求

实现 `solution.py` 里的 `UploadServer` 和 `upload_file`。哈希一律用 `sha256_hex(data)`（已经写好了），返回 64 位小写十六进制字符串。

### 1. `UploadServer(chunk_size, *, clock=time.monotonic, session_ttl=86400.0, max_file_size=50 * 2**30)`

- `chunk_size < 1` 或 `session_ttl <= 0` 抛 `ValueError`。属性 `chunk_size`。
- `has_file(sha256) -> bool`：服务端是否已经存有这个哈希的文件（秒传用）。
- `create_session(name, total_size, sha256) -> upload_id`：`total_size` 不在 `(0, max_file_size]` 里抛 `ValueError`。返回一个唯一的字符串。块数 = `ceil(total_size / chunk_size)`。
- `num_chunks(upload_id) -> int`。
- `upload_chunk(upload_id, index, data, chunk_sha256)`：
  - 会话不存在（或已过期、已完成）抛 `KeyError`；`index` 越界抛 `IndexError`。
  - 大小不对抛 `ValueError`：除最后一块外，每块必须 **正好** `chunk_size` 字节；最后一块必须正好是剩下的字节数。
  - `sha256_hex(data) != chunk_sha256` 抛 `ChecksumError`（数据在路上损坏了）。
  - 这一块已经收到过：内容完全一样就什么都不做（网络重试导致的重复上传，**幂等**）；内容不一样抛 `ChunkConflictError`。
  - 成功（包括幂等的重复上传）时，刷新会话的「最后活动时间」。
- `missing_chunks(upload_id) -> list[int]`：还没收到的块的下标，升序。同样会刷新最后活动时间。会话不存在抛 `KeyError`。
- `complete(upload_id) -> file_id`：
  - 还有块没到，抛 `IncompleteUploadError`，它的 `missing` 属性是缺的块的列表；会话保留，可以继续传。
  - 都到了：按顺序拼起来，**无论成功失败，会话都删除**。整体哈希和创建时声明的不一致，抛 `ChecksumError`（文件不保存）；一致则保存文件，返回 `file_id`（就是整体的 sha256），之后 `has_file` 返回 `True`。
- `get_file(file_id) -> bytes`。
- **过期清理**：会话的最后活动时间距离现在 `>= session_ttl`，就算过期。过期的会话在下一次任何会话相关的调用时被删除（惰性清理），它占用的块也一起释放。`active_sessions() -> int` 返回当前未过期的会话数。

### 2. `upload_file(server, name, data, *, max_attempts=3, upload_id=None) -> UploadResult`

客户端上传逻辑。`UploadResult(file_id, upload_id, chunks_sent, deduplicated)` 已经定义好。

1. 先算整体哈希。如果 `server.has_file(...)`，直接返回 `UploadResult(哈希, None, 0, True)`（秒传）。
2. 如果给了 `upload_id`（断点续传）：用 `missing_chunks` 问还缺哪些块。如果这个会话已经不存在了（`KeyError`，比如过期了），就当作没给 `upload_id`。
3. 没有可用的 `upload_id`：`create_session` 新建一个，缺的就是全部块。
4. 按下标顺序上传缺的块，块大小用 `server.chunk_size`。每一块遇到 `ConnectionError` 或 `ChecksumError` 就立刻重试这一块，**每块** 最多尝试 `max_attempts` 次。某一块用完了次数还失败，抛 `UploadInterrupted`，它的 `upload_id` 属性是当前会话 ID（让调用方以后可以续传），并用 `raise ... from 原异常` 保留原因。其他异常不重试，直接抛出。
5. 全部传完后 `complete`，返回 `UploadResult(file_id, upload_id, 本次成功上传的块数, False)`。
- `max_attempts < 1` 抛 `ValueError`。

## 接口

```python
server = UploadServer(chunk_size=5 * 2**20)
try:
    r = upload_file(server, "video.mp4", data)
except UploadInterrupted as e:
    saved_id = e.upload_id          # 存到本地，下次启动时续传
...
r = upload_file(server, "video.mp4", data, upload_id=saved_id)
r.chunks_sent                       # 只传了缺的那几块
```

函数签名见 `solution.py`，不要改。

## 验收

```bash
pytest days/day-17/1-resumable-upload
```

共 29 个测试。建议顺序：`-k server` → `-k expire` → `-k client`。

## 进阶（可选）

- 现在是一块一块串行上传的。改成 **并发** 上传（比如同时传 4 块），服务端需要注意什么？客户端怎么限制并发数、怎么处理部分块失败？
- 块现在存在服务端的内存里。真实系统里块直接存到对象存储（S3 的 Multipart Upload），合并只是在元数据里记录「这个文件由哪几块组成」，不用真的把字节拼起来。这样做有什么好处？
- 服务端不信任客户端声明的哈希：一个恶意用户可以声称「我要上传的文件哈希是 X」（X 是别人的私密文件），然后触发秒传，拿到别人的文件。怎么防？（提示：让客户端证明它真的有这个文件，比如随机抽查文件中某一段的哈希）
- 弱网环境下块大小怎么选？能不能根据网速动态调整？

## 面试追问（做完后自己先想想）

- 为什么每块都要有自己的校验和，最后还要再校验一次整体哈希？只做其中一个够吗？
- 上传会话要保留多久？太短和太长各有什么问题？过期清理放在后台定时任务里做，和今天这样惰性清理，各有什么优缺点？
- 一个 50 GB 的文件、5 MB 一块，有多少块？`missing_chunks` 返回一个上万项的列表合适吗？（S3 的 `ListParts` 是分页的）
- 视频平台上传完以后还有转码、审核等很多步骤，用户的「上传成功」应该在哪一步告诉他？（今天的设计题）
