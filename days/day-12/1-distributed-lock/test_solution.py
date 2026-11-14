import importlib.util
import sys
import threading
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day12_lock_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
LockServer = _mod.LockServer
FencedStorage = _mod.FencedStorage
LockClient = _mod.LockClient
Lease = _mod.Lease
StaleTokenError = _mod.StaleTokenError
LockNotAcquiredError = _mod.LockNotAcquiredError
LockNotHeldError = _mod.LockNotHeldError


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class SlowServer:
    """包一层服务端：请求在去程花 before 秒，回程花 after 秒（模拟网络延迟）。"""

    def __init__(self, server, clock, before=0.0, after=0.0):
        self.server, self.clock, self.before, self.after = server, clock, before, after

    def __getattr__(self, name):
        target = getattr(self.server, name)

        def call(*args, **kwargs):
            self.clock.advance(self.before)
            result = target(*args, **kwargs)
            self.clock.advance(self.after)
            return result

        return call


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def server(clock):
    return LockServer(clock=clock)


# =====================================================================
# 锁服务
# =====================================================================


def test_server_acquire_and_holder(server):
    lease = server.acquire("job", "a", 10)
    assert lease == Lease("job", "a", 1, 1010.0)
    assert server.holder("job") == lease
    assert server.holder("other") is None


def test_server_mutual_exclusion(server):
    assert server.acquire("job", "a", 10)
    assert server.acquire("job", "b", 10) is None
    assert server.acquire("job", "a", 10) is None, "不可重入"
    assert server.acquire("other", "b", 10).token == 1, "不同的锁互不影响，令牌各自计数"


def test_server_expiry(server, clock):
    server.acquire("job", "a", 10)
    clock.advance(9.99)
    assert server.acquire("job", "b", 10) is None
    clock.advance(0.01)
    assert server.holder("job") is None
    lease = server.acquire("job", "b", 10)
    assert lease.owner == "b" and lease.token == 2


def test_server_tokens_monotonic_across_owners(server, clock):
    tokens = []
    for owner in ["a", "b", "a", "c"]:
        lease = server.acquire("job", owner, 5)
        tokens.append(lease.token)
        if owner == "b":
            clock.advance(5)  # 过期而不是释放
        else:
            assert server.release("job", owner, lease.token)
    assert tokens == [1, 2, 3, 4]


def test_server_renew(server, clock):
    lease = server.acquire("job", "a", 10)
    clock.advance(8)
    assert server.renew("job", "a", lease.token, 10) is True
    assert server.holder("job").expires_at == 1018.0
    clock.advance(9)
    assert server.holder("job") is not None


def test_server_renew_checks_owner_and_token(server):
    lease = server.acquire("job", "a", 10)
    assert server.renew("job", "b", lease.token, 10) is False
    assert server.renew("job", "a", lease.token + 1, 10) is False
    assert server.renew("nope", "a", lease.token, 10) is False


def test_server_cannot_renew_expired_even_if_free(server, clock):
    lease = server.acquire("job", "a", 10)
    clock.advance(10)
    assert server.renew("job", "a", lease.token, 10) is False
    assert server.holder("job") is None


def test_server_release_only_by_current_holder(server, clock):
    old = server.acquire("job", "a", 10)
    clock.advance(10)
    new = server.acquire("job", "b", 10)
    assert server.release("job", "a", old.token) is False, "过期的旧持有者不能删掉新持有者的锁"
    assert server.holder("job") == new
    assert server.release("job", "b", new.token) is True
    assert server.release("job", "b", new.token) is False
    assert server.holder("job") is None


def test_server_invalid_ttl(server):
    with pytest.raises(ValueError):
        server.acquire("job", "a", 0)
    lease = server.acquire("job", "a", 5)
    with pytest.raises(ValueError):
        server.renew("job", "a", lease.token, -1)


def test_server_thread_safe():
    server = LockServer()
    winners = []
    barrier = threading.Barrier(16)

    def contend(i):
        barrier.wait()
        if server.acquire("job", f"w{i}", 60):
            winners.append(i)

    threads = [threading.Thread(target=contend, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


# =====================================================================
# fencing
# =====================================================================


def test_fence_accepts_increasing_and_equal_tokens():
    s = FencedStorage()
    assert s.max_token == 0
    s.write("x", 1, token=3)
    s.write("x", 2, token=3)
    s.write("y", 9, token=5)
    assert s.read("x") == 2 and s.read("y") == 9
    assert s.max_token == 5


def test_fence_rejects_stale_token():
    s = FencedStorage()
    s.write("x", "new", token=34)
    with pytest.raises(StaleTokenError):
        s.write("x", "old", token=33)
    assert s.read("x") == "new"
    with pytest.raises(StaleTokenError):
        s.write("other-key", "old", token=33)  # 整个存储共用一个最大令牌号
    assert s.read("other-key", "dflt") == "dflt"
    assert s.max_token == 34


# =====================================================================
# 客户端
# =====================================================================


def test_client_acquire_and_token(server, clock):
    c = LockClient(server, "a", clock=clock)
    assert c.acquire("job", 10) is True
    assert c.is_held("job")
    assert c.token("job") == 1
    assert LockClient(server, "b", clock=clock).acquire("job", 10) is False


def test_client_local_validity_includes_drift(server, clock):
    c = LockClient(server, "a", clock=clock, drift_factor=0.1)
    c.acquire("job", 10)
    clock.advance(8.99)
    assert c.is_held("job")
    clock.advance(0.01)  # 本地截止 = 1000 + 10 - 1 = 1009，服务端还要再等 1 秒才过期
    assert not c.is_held("job")
    assert server.holder("job") is not None
    with pytest.raises(LockNotHeldError):
        c.token("job")


def test_client_validity_counted_from_before_request(server, clock):
    slow = SlowServer(server, clock, before=1.0, after=2.0)
    c = LockClient(slow, "a", clock=clock, drift_factor=0.0)
    assert c.acquire("job", 10)
    assert clock() == 1003.0
    clock.advance(6.99)  # 1009.99 < 1000 + 10
    assert c.is_held("job")
    clock.advance(0.01)
    assert not c.is_held("job"), "本地有效期要从发请求之前算，而不是从收到响应时算"


def test_client_gives_up_if_request_too_slow(server, clock):
    slow = SlowServer(server, clock, before=1.0, after=10.0)
    c = LockClient(slow, "a", clock=clock, drift_factor=0.0)
    assert c.acquire("job", 10) is False
    assert not c.is_held("job")
    assert server.holder("job") is None, "拿到时已经过期的锁要立刻释放"


def test_client_renew_extends(server, clock):
    c = LockClient(server, "a", clock=clock, drift_factor=0.0)
    c.acquire("job", 10)
    clock.advance(9)
    assert c.renew("job") is True
    clock.advance(9)
    assert c.is_held("job")
    assert server.holder("job").expires_at == 1019.0


def test_client_does_not_renew_locally_expired(server, clock):
    calls = []

    class Spy(SlowServer):
        def __getattr__(self, name):
            calls.append(name)
            return super().__getattr__(name)

    c = LockClient(Spy(server, clock), "a", clock=clock, drift_factor=0.1)
    c.acquire("job", 10)
    clock.advance(9.5)  # 本地已过期，服务端还没过期
    assert c.renew("job") is False
    assert calls == ["acquire"], "本地已经认为丢锁了，就不要再去续租"
    assert c.release("job") is False


def test_client_renew_failure_drops_lock(server, clock):
    c = LockClient(server, "a", clock=clock, drift_factor=0.0)
    c.acquire("job", 10)
    lease = server.holder("job")
    server.release("job", "a", lease.token)  # 比如运维手动清掉了锁
    assert c.renew("job") is False
    assert not c.is_held("job")


def test_client_release(server, clock):
    c = LockClient(server, "a", clock=clock)
    assert c.release("job") is False
    c.acquire("job", 10)
    assert c.release("job") is True
    assert not c.is_held("job")
    assert server.holder("job") is None


def test_client_context_manager(server, clock):
    c = LockClient(server, "a", clock=clock)
    with c.lock("job", 10) as token:
        assert token == 1
        assert server.holder("job").owner == "a"
    assert server.holder("job") is None


def test_client_context_manager_releases_on_error(server, clock):
    c = LockClient(server, "a", clock=clock)
    with pytest.raises(ZeroDivisionError):
        with c.lock("job", 10):
            1 / 0
    assert server.holder("job") is None


def test_client_context_manager_not_acquired(server, clock):
    server.acquire("job", "someone-else", 10)
    c = LockClient(server, "a", clock=clock)
    with pytest.raises(LockNotAcquiredError):
        with c.lock("job", 10):
            pytest.fail("不应该进入")


@pytest.mark.parametrize("drift", [-0.1, 1.0, 2])
def test_client_invalid_drift(server, drift):
    with pytest.raises(ValueError):
        LockClient(server, "a", drift_factor=drift)


# =====================================================================
# 场景：GC 停顿导致两个「持有者」
# =====================================================================


def test_scenario_gc_pause_is_stopped_by_fencing(server, clock):
    storage = FencedStorage()
    a = LockClient(server, "a", clock=clock, drift_factor=0.0)
    b = LockClient(server, "b", clock=clock, drift_factor=0.0)

    assert a.acquire("file", 10)
    token_a = a.token("file")       # a 在开始写之前取到了令牌，然后……
    clock.advance(30)               # ……进入了 30 秒的 GC 停顿

    assert b.acquire("file", 10)    # 租约过期，b 拿到了锁
    storage.write("file", "written by b", b.token("file"))

    # a 醒来，它以为自己还在临界区里，拿着旧令牌继续写
    with pytest.raises(StaleTokenError):
        storage.write("file", "written by a", token_a)
    assert storage.read("file") == "written by b"

    # a 如果在写之前检查一下 is_held，就能自己发现
    assert not a.is_held("file")
    assert a.release("file") is False
    assert server.holder("file").owner == "b"


def test_scenario_renewing_holder_keeps_lock(server, clock):
    storage = FencedStorage()
    a = LockClient(server, "a", clock=clock)
    b = LockClient(server, "b", clock=clock)
    assert a.acquire("file", 10)
    for _ in range(12):             # 1 分钟里每 5 秒续一次租
        clock.advance(5)
        assert a.renew("file")
        assert b.acquire("file", 10) is False
    storage.write("file", "a", a.token("file"))
    assert a.release("file")
    assert b.acquire("file", 10)
    assert b.token("file") == 2
    storage.write("file", "b", b.token("file"))
    assert storage.read("file") == "b"
