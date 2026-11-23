import importlib.util
import sys
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day20_saga_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
TransientError = _mod.TransientError
Step = _mod.Step
SagaResult = _mod.SagaResult
SagaLog = _mod.SagaLog
SagaOrchestrator = _mod.SagaOrchestrator


class Crash(BaseException):
    """模拟进程在执行到一半时被 kill -9。不是 Exception，编排器不应该捕获它。"""


class Hotel:
    """一个小型的酒店预订世界：房间库存、钱包、通知。记录每一次调用。"""

    def __init__(self, rooms=1, balance=1000):
        self.rooms = rooms
        self.balance = balance
        self.calls = []
        self.fail = {}      # 名字 -> 要抛出的异常列表，按顺序消耗
        self.crash_after = None  # 某个动作 **执行完成后** 崩溃（还没来得及写日志）

    def _maybe_fail(self, name):
        self.calls.append(name)
        errs = self.fail.get(name)
        if errs:
            raise errs.pop(0)

    def _maybe_crash(self, name):
        if self.crash_after == name:
            self.crash_after = None
            raise Crash(name)

    def reserve(self, ctx):
        self._maybe_fail("reserve")
        if self.rooms < 1:
            raise RuntimeError("sold out")
        self.rooms -= 1
        self._maybe_crash("reserve")
        return "R-1"

    def release(self, ctx):
        self._maybe_fail("release")
        assert ctx["reserve"] == "R-1", "补偿时要能拿到前面步骤的结果"
        self.rooms += 1

    def charge(self, ctx):
        self._maybe_fail("charge")
        if self.balance < ctx["price"]:
            raise RuntimeError("insufficient funds")
        self.balance -= ctx["price"]
        self._maybe_crash("charge")
        return {"txn": "T-9", "amount": ctx["price"]}

    def refund(self, ctx):
        self._maybe_fail("refund")
        self.balance += ctx["charge"]["amount"]

    def notify(self, ctx):
        self._maybe_fail("notify")
        return "sent"

    def steps(self, notify_retries=0):
        return [
            Step("reserve", self.reserve, self.release),
            Step("charge", self.charge, self.refund, retries=2),
            Step("notify", self.notify, None, retries=notify_retries),
        ]


def make(**kw):
    return SagaOrchestrator(SagaLog(), **kw)


# =====================================================================
# 日志
# =====================================================================


def test_log_basics():
    log = SagaLog()
    assert "a" not in log
    assert log.events("a") == []
    log.append("a", ("started",))
    log.append("a", ["finished", "succeeded"])
    assert "a" in log
    assert log.events("a") == [("started",), ("finished", "succeeded")]
    log.events("a").append(("junk",))
    assert len(log.events("a")) == 2, "返回副本"


# =====================================================================
# 正常执行与参数检查
# =====================================================================


def test_happy_path():
    h = Hotel()
    o = make()
    ctx = {"price": 300}
    r = o.run("s1", h.steps(), ctx)
    assert r == SagaResult("succeeded", None, None)
    assert h.calls == ["reserve", "charge", "notify"]
    assert ctx["reserve"] == "R-1" and ctx["charge"]["txn"] == "T-9" and ctx["notify"] == "sent"
    assert h.rooms == 0 and h.balance == 700
    assert o.status("s1") == "succeeded"
    assert o.log.events("s1") == [
        ("started",),
        ("step_succeeded", "reserve", "R-1"),
        ("step_succeeded", "charge", {"txn": "T-9", "amount": 300}),
        ("step_succeeded", "notify", "sent"),
        ("finished", "succeeded"),
    ]


def test_ctx_defaults_to_new_dict():
    o = make()
    r = o.run("s", [Step("a", lambda c: 1)])
    assert r.status == "succeeded"


def test_invalid_args():
    with pytest.raises(ValueError):
        make(compensation_retries=-1)
    o = make()
    noop = lambda c: None  # noqa: E731
    with pytest.raises(ValueError):
        o.run("s", [])
    with pytest.raises(ValueError):
        o.run("s", [Step("a", noop), Step("a", noop)])
    with pytest.raises(ValueError):
        o.run("s", [Step("a", noop, retries=-1)])
    assert "s" not in o.log, "参数不对就不应该开始"


def test_duplicate_saga_id_rejected():
    o = make()
    o.run("s", [Step("a", lambda c: 1)])
    with pytest.raises(ValueError):
        o.run("s", [Step("a", lambda c: 1)])


def test_status_unknown():
    with pytest.raises(KeyError):
        make().status("nope")


# =====================================================================
# 失败与补偿
# =====================================================================


def test_first_step_fails_nothing_to_compensate():
    h = Hotel(rooms=0)
    o = make()
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "compensated" and r.failed_step == "reserve"
    assert isinstance(r.error, RuntimeError)
    assert h.calls == ["reserve"]
    assert o.log.events("s")[-1] == ("finished", "compensated")


def test_middle_step_fails_compensates_previous():
    h = Hotel(balance=100)
    o = make()
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "compensated" and r.failed_step == "charge"
    assert h.rooms == 1, "房间要还回去"
    assert h.calls == ["reserve", "charge", "release"]
    ev = o.log.events("s")
    assert ev[2][0:2] == ("step_failed", "charge")
    assert isinstance(ev[2][2], str), "日志里存异常的 repr 字符串"
    assert ev[3:] == [("compensated", "reserve"), ("finished", "compensated")]


def test_last_step_fails_compensates_in_reverse_order():
    h = Hotel()
    h.fail["notify"] = [RuntimeError("smtp down")]
    o = make()
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "compensated" and r.failed_step == "notify"
    assert h.calls == ["reserve", "charge", "notify", "refund", "release"]
    assert h.rooms == 1 and h.balance == 1000
    assert [e for e in o.log.events("s") if e[0] == "compensated"] == [
        ("compensated", "charge"), ("compensated", "reserve")]


def test_step_without_compensation_is_logged_as_compensated():
    o = make()
    calls = []
    steps = [
        Step("read", lambda c: calls.append("read") or 1),  # 只读步骤，没有补偿
        Step("boom", lambda c: (_ for _ in ()).throw(RuntimeError())),
    ]
    r = o.run("s", steps)
    assert r.status == "compensated"
    assert ("compensated", "read") in o.log.events("s")


def test_transient_errors_are_retried():
    h = Hotel()
    h.fail["charge"] = [TransientError(), TransientError()]
    o = make()
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "succeeded"
    assert h.calls == ["reserve", "charge", "charge", "charge", "notify"]


def test_transient_errors_exhaust_retries():
    h = Hotel()
    h.fail["charge"] = [TransientError()] * 3
    o = make()
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "compensated" and isinstance(r.error, TransientError)
    assert h.calls == ["reserve", "charge", "charge", "charge", "release"]


def test_non_transient_errors_not_retried():
    h = Hotel()
    h.fail["charge"] = [ValueError("card declined")]
    o = make()
    o.run("s", h.steps(), {"price": 300})
    assert h.calls.count("charge") == 1


def test_compensation_retried_until_success():
    h = Hotel()
    h.fail["notify"] = [RuntimeError()]
    h.fail["refund"] = [RuntimeError(), TransientError()]  # 补偿遇到任何 Exception 都重试
    o = make(compensation_retries=2)
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "compensated"
    assert h.calls.count("refund") == 3
    assert h.balance == 1000


def test_compensation_gives_up_stuck():
    h = Hotel()
    h.fail["notify"] = [RuntimeError()]
    h.fail["refund"] = [RuntimeError()] * 10
    o = make(compensation_retries=2)
    r = o.run("s", h.steps(), {"price": 300})
    assert r.status == "stuck" and r.failed_step == "notify"
    assert h.calls.count("refund") == 3
    assert "release" not in h.calls, "补偿卡住就停下，不继续往前补偿"
    assert o.log.events("s")[-2:] == [("compensation_failed", "charge"), ("finished", "stuck")]
    assert o.status("s") == "stuck"


def test_crash_is_not_swallowed():
    h = Hotel()
    h.crash_after = "charge"
    o = make()
    with pytest.raises(Crash):
        o.run("s", h.steps(), {"price": 300})
    assert o.status("s") == "running"
    assert o.log.events("s")[-1] == ("step_succeeded", "reserve", "R-1")


# =====================================================================
# 崩溃恢复
# =====================================================================


def test_recover_unknown():
    with pytest.raises(KeyError):
        make().recover("nope", Hotel().steps())


def test_recover_finished_saga_does_nothing():
    h = Hotel()
    o = make()
    o.run("s", h.steps(), {"price": 300})
    h.calls.clear()
    r = o.recover("s", h.steps(), {"price": 300})
    assert r == SagaResult("succeeded", None, None)
    assert h.calls == []


def test_recover_continues_forward_and_rebuilds_ctx():
    h = Hotel()
    h.crash_after = "charge"  # 扣款成功了，但日志还没写
    o = make()
    with pytest.raises(Crash):
        o.run("s", h.steps(), {"price": 300})
    h.calls.clear()
    ctx = {"price": 300}  # 新进程：ctx 里只有输入，没有前面步骤的结果
    r = o.recover("s", h.steps(), ctx)
    assert r.status == "succeeded"
    assert ctx["reserve"] == "R-1", "从日志里恢复已完成步骤的结果"
    assert h.calls == ["charge", "notify"], "reserve 不能再执行；charge 没有记录，要重新执行"
    assert h.balance == 400, "所以动作必须幂等（真实系统要用幂等键，Day 11）"


def test_recover_during_compensation():
    h = Hotel()
    h.fail["notify"] = [RuntimeError()]
    o = make()

    real_release = h.release

    def crashing_release(ctx):
        real_release(ctx)
        raise Crash("release")

    steps = h.steps()
    steps[0] = Step("reserve", h.reserve, crashing_release)
    with pytest.raises(Crash):
        o.run("s", steps, {"price": 300})
    assert o.status("s") == "compensating"
    h.calls.clear()
    r = o.recover("s", h.steps(), {"price": 300})
    assert r.status == "compensated" and r.failed_step == "notify"
    assert h.calls == ["release"], "refund 已经记录完成，不再执行；release 没记录，要重新执行"


def test_recover_crash_before_any_step():
    h = Hotel(rooms=2)
    h.crash_after = "reserve"
    o = make()
    with pytest.raises(Crash):
        o.run("s", h.steps(), {"price": 300})
    assert o.log.events("s") == [("started",)]
    r = o.recover("s", h.steps(), {"price": 300})
    assert r.status == "succeeded"
    assert h.rooms == 0, "reserve 跑了两次，占了两间房：这就是不幂等的后果"
