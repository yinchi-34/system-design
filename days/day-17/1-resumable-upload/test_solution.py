import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day17_upload_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
UploadServer = _mod.UploadServer
upload_file = _mod.upload_file
sha256_hex = _mod.sha256_hex
ChecksumError = _mod.ChecksumError
ChunkConflictError = _mod.ChunkConflictError
IncompleteUploadError = _mod.IncompleteUploadError
UploadInterrupted = _mod.UploadInterrupted
UploadResult = _mod.UploadResult


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


CS = 10  # 测试用的小块：10 字节


def chunks(data, cs=CS):
    return [data[i:i + cs] for i in range(0, len(data), cs)]


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def server(clock):
    return UploadServer(CS, clock=clock, session_ttl=100)


def start(server, data, name="f.bin"):
    return server.create_session(name, len(data), sha256_hex(data))


def send(server, uid, data, idx):
    c = chunks(data)[idx]
    server.upload_chunk(uid, idx, c, sha256_hex(c))


# =====================================================================
# 服务端
# =====================================================================


def test_server_full_flow(server):
    data = os.urandom(35)
    uid = start(server, data)
    assert server.num_chunks(uid) == 4
    assert server.missing_chunks(uid) == [0, 1, 2, 3]
    for i in (2, 0, 3, 1):  # 顺序无所谓
        send(server, uid, data, i)
    assert server.missing_chunks(uid) == []
    fid = server.complete(uid)
    assert fid == sha256_hex(data)
    assert server.has_file(fid)
    assert server.get_file(fid) == data


def test_server_exact_multiple_of_chunk_size(server):
    data = os.urandom(30)
    uid = start(server, data)
    assert server.num_chunks(uid) == 3
    for i in range(3):
        send(server, uid, data, i)
    assert server.complete(uid) == sha256_hex(data)


def test_server_unique_upload_ids(server):
    data = b"x" * 5
    assert len({start(server, data) for _ in range(100)}) == 100


@pytest.mark.parametrize("size", [0, -1, 1001])
def test_server_invalid_size(clock, size):
    s = UploadServer(CS, clock=clock, max_file_size=1000)
    with pytest.raises(ValueError):
        s.create_session("f", size, "0" * 64)


def test_server_invalid_args():
    with pytest.raises(ValueError):
        UploadServer(0)
    with pytest.raises(ValueError):
        UploadServer(10, session_ttl=0)


def test_server_unknown_session(server):
    with pytest.raises(KeyError):
        server.upload_chunk("nope", 0, b"x", sha256_hex(b"x"))
    with pytest.raises(KeyError):
        server.missing_chunks("nope")
    with pytest.raises(KeyError):
        server.complete("nope")


def test_server_index_out_of_range(server):
    uid = start(server, b"x" * 25)
    with pytest.raises(IndexError):
        server.upload_chunk(uid, 3, b"x" * 5, sha256_hex(b"x" * 5))
    with pytest.raises(IndexError):
        server.upload_chunk(uid, -1, b"x" * 10, sha256_hex(b"x" * 10))


def test_server_wrong_chunk_size(server):
    uid = start(server, b"x" * 25)
    with pytest.raises(ValueError):
        server.upload_chunk(uid, 0, b"x" * 9, sha256_hex(b"x" * 9))
    with pytest.raises(ValueError):
        server.upload_chunk(uid, 2, b"x" * 10, sha256_hex(b"x" * 10))  # 最后一块只能是 5 字节
    server.upload_chunk(uid, 2, b"x" * 5, sha256_hex(b"x" * 5))
    assert server.missing_chunks(uid) == [0, 1]


def test_server_checksum_mismatch(server):
    data = os.urandom(20)
    uid = start(server, data)
    c = chunks(data)[0]
    with pytest.raises(ChecksumError):
        server.upload_chunk(uid, 0, c, sha256_hex(c + b"!"))
    assert server.missing_chunks(uid) == [0, 1], "校验失败的块不能记下来"


def test_server_duplicate_chunk_is_idempotent(server):
    data = os.urandom(20)
    uid = start(server, data)
    send(server, uid, data, 0)
    send(server, uid, data, 0)  # 网络重试
    assert server.missing_chunks(uid) == [1]


def test_server_conflicting_chunk(server):
    data = os.urandom(20)
    uid = start(server, data)
    send(server, uid, data, 0)
    other = b"y" * 10
    with pytest.raises(ChunkConflictError):
        server.upload_chunk(uid, 0, other, sha256_hex(other))


def test_server_complete_incomplete(server):
    data = os.urandom(35)
    uid = start(server, data)
    send(server, uid, data, 1)
    with pytest.raises(IncompleteUploadError) as ei:
        server.complete(uid)
    assert ei.value.missing == [0, 2, 3]
    assert server.missing_chunks(uid) == [0, 2, 3], "会话要保留，可以继续传"


def test_server_complete_whole_hash_mismatch(server):
    data = os.urandom(20)
    uid = server.create_session("f", 20, sha256_hex(b"something else"))
    for i in range(2):
        send(server, uid, data, i)
    with pytest.raises(ChecksumError):
        server.complete(uid)
    assert not server.has_file(sha256_hex(data))
    with pytest.raises(KeyError):
        server.missing_chunks(uid)


def test_server_session_gone_after_complete(server):
    data = b"abc"
    uid = start(server, data)
    send(server, uid, data, 0)
    server.complete(uid)
    with pytest.raises(KeyError):
        server.complete(uid)
    assert server.active_sessions() == 0


# =====================================================================
# 会话过期
# =====================================================================


def test_expire_after_ttl(server, clock):
    data = os.urandom(30)
    uid = start(server, data)
    clock.advance(99.9)
    assert server.active_sessions() == 1
    clock.advance(0.1)
    assert server.active_sessions() == 0
    with pytest.raises(KeyError):
        send(server, uid, data, 0)


def test_expire_activity_refreshes(server, clock):
    data = os.urandom(30)
    uid = start(server, data)
    for i in range(3):
        clock.advance(60)
        send(server, uid, data, i)  # 每次上传都刷新
    clock.advance(60)
    assert server.missing_chunks(uid) == []
    clock.advance(99)
    assert server.complete(uid) == sha256_hex(data)


def test_expire_missing_chunks_refreshes(server, clock):
    uid = start(server, b"x" * 15)
    clock.advance(90)
    server.missing_chunks(uid)
    clock.advance(90)
    assert server.active_sessions() == 1


def test_expire_failed_upload_does_not_refresh(server, clock):
    data = os.urandom(20)
    uid = start(server, data)
    clock.advance(90)
    with pytest.raises(ChecksumError):
        server.upload_chunk(uid, 0, chunks(data)[0], "0" * 64)
    clock.advance(10)
    assert server.active_sessions() == 0


def test_expire_only_stale_sessions(server, clock):
    old = start(server, b"old")
    clock.advance(50)
    new = start(server, b"new")
    clock.advance(50)
    with pytest.raises(KeyError):
        server.missing_chunks(old)
    assert server.missing_chunks(new) == [0]


# =====================================================================
# 客户端
# =====================================================================


class Flaky:
    """包一层服务端：按计划让某些 upload_chunk 调用失败。"""

    def __init__(self, server, fail_plan=None, corrupt_plan=None, dead_after=None):
        self.server = server
        self.fail_plan = dict(fail_plan or {})       # index -> 失败次数（ConnectionError）
        self.corrupt_plan = dict(corrupt_plan or {})  # index -> 损坏次数（数据被改了一个字节）
        self.dead_after = dead_after                  # 成功上传这么多块以后网络彻底断掉
        self.ok = 0
        self.calls = []

    @property
    def chunk_size(self):
        return self.server.chunk_size

    def __getattr__(self, name):
        return getattr(self.server, name)

    def upload_chunk(self, uid, index, data, chunk_sha):
        self.calls.append(index)
        if self.dead_after is not None and self.ok >= self.dead_after:
            raise ConnectionError("network down")
        if self.fail_plan.get(index, 0) > 0:
            self.fail_plan[index] -= 1
            raise ConnectionError("timeout")
        if self.corrupt_plan.get(index, 0) > 0:
            self.corrupt_plan[index] -= 1
            data = bytes([data[0] ^ 1]) + data[1:]
        self.server.upload_chunk(uid, index, data, chunk_sha)
        self.ok += 1


def test_client_simple_upload(server):
    data = os.urandom(45)
    r = upload_file(server, "a.bin", data)
    assert isinstance(r, UploadResult)
    assert r.file_id == sha256_hex(data) and r.chunks_sent == 5 and r.deduplicated is False
    assert r.upload_id is not None
    assert server.get_file(r.file_id) == data


def test_client_instant_upload_when_exists(server):
    data = os.urandom(45)
    upload_file(server, "a.bin", data)
    spy = Flaky(server)
    r = upload_file(spy, "copy.bin", data)
    assert r == UploadResult(sha256_hex(data), None, 0, True)
    assert spy.calls == [], "秒传不应该上传任何块"


def test_client_retries_transient_errors(server):
    data = os.urandom(45)
    flaky = Flaky(server, fail_plan={1: 2, 3: 1}, corrupt_plan={4: 2})
    r = upload_file(flaky, "a.bin", data, max_attempts=3)
    assert r.file_id == sha256_hex(data)
    assert r.chunks_sent == 5
    assert flaky.calls == [0, 1, 1, 1, 2, 3, 3, 4, 4, 4]


def test_client_gives_up_and_can_resume(server):
    data = os.urandom(95)  # 10 块
    flaky = Flaky(server, dead_after=6)
    with pytest.raises(UploadInterrupted) as ei:
        upload_file(flaky, "big.bin", data, max_attempts=2)
    assert isinstance(ei.value.__cause__, ConnectionError), "用 raise ... from 保留原因"
    uid = ei.value.upload_id
    assert server.missing_chunks(uid) == [6, 7, 8, 9]

    spy = Flaky(server)
    r = upload_file(spy, "big.bin", data, upload_id=uid)
    assert r.upload_id == uid
    assert r.chunks_sent == 4
    assert spy.calls == [6, 7, 8, 9], "续传只传缺的块"
    assert server.get_file(r.file_id) == data


def test_client_resume_expired_session_starts_over(server, clock):
    data = os.urandom(30)
    flaky = Flaky(server, dead_after=2)
    with pytest.raises(UploadInterrupted) as ei:
        upload_file(flaky, "a.bin", data, max_attempts=1)
    clock.advance(1000)  # 会话过期了
    r = upload_file(server, "a.bin", data, upload_id=ei.value.upload_id)
    assert r.upload_id != ei.value.upload_id
    assert r.chunks_sent == 3


def test_client_non_retryable_error_propagates(server):
    class Broken(Flaky):
        def upload_chunk(self, *a):
            self.calls.append(a[1])
            raise PermissionError("quota exceeded")

    b = Broken(server)
    with pytest.raises(PermissionError):
        upload_file(b, "a.bin", os.urandom(30))
    assert b.calls == [0], "其他异常不重试"


def test_client_invalid_attempts(server):
    with pytest.raises(ValueError):
        upload_file(server, "a", b"x", max_attempts=0)


def test_client_small_file_single_chunk(server):
    r = upload_file(server, "tiny", b"hi")
    assert r.chunks_sent == 1
    assert server.get_file(r.file_id) == b"hi"
