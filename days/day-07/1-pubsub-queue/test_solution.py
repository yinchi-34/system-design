import importlib.util
import sys
import threading
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day07_mq_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # dataclass 需要模块已注册
_spec.loader.exec_module(_mod)
Broker = _mod.Broker
Message = _mod.Message


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


TOPIC, G = "orders", "notify"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def broker(clock):
    b = Broker(ack_timeout=10, max_deliveries=3, clock=clock)
    b.create_topic(TOPIC)
    b.subscribe(TOPIC, G)
    return b


def payloads(msgs):
    return [m.payload for m in msgs]


# =====================================================================
# 基本收发、扇出、消费者组
# =====================================================================


def test_basic_publish_poll_ack(broker):
    mid = broker.publish(TOPIC, "hello")
    [m] = broker.poll(TOPIC, G)
    assert isinstance(m, Message)
    assert (m.message_id, m.payload, m.delivery_count) == (mid, "hello", 1)
    assert m.receipt
    assert broker.ack(TOPIC, G, m.receipt) is True
    assert broker.poll(TOPIC, G) == []


def test_basic_poll_empty(broker):
    assert broker.poll(TOPIC, G, max_messages=10) == []


def test_basic_fifo_and_max_messages(broker):
    for i in range(5):
        broker.publish(TOPIC, i)
    assert payloads(broker.poll(TOPIC, G, max_messages=3)) == [0, 1, 2]
    assert payloads(broker.poll(TOPIC, G, max_messages=3)) == [3, 4]
    assert broker.poll(TOPIC, G, max_messages=3) == []


def test_basic_max_messages_invalid(broker):
    with pytest.raises(ValueError):
        broker.poll(TOPIC, G, max_messages=0)


def test_basic_payload_passed_through_unchanged(broker):
    obj = {"order_id": 42, "items": [1, 2]}
    broker.publish(TOPIC, obj)
    [m] = broker.poll(TOPIC, G)
    assert m.payload is obj


def test_basic_message_ids_unique(broker):
    ids = {broker.publish(TOPIC, i) for i in range(1000)}
    assert len(ids) == 1000


@pytest.mark.parametrize("kwargs", [{"ack_timeout": 0}, {"ack_timeout": -1}, {"max_deliveries": 0}])
def test_basic_invalid_constructor(kwargs):
    with pytest.raises(ValueError):
        Broker(**kwargs)


def test_basic_unknown_topic_or_group(broker):
    with pytest.raises(KeyError):
        broker.publish("nope", 1)
    with pytest.raises(KeyError):
        broker.subscribe("nope", G)
    with pytest.raises(KeyError):
        broker.poll(TOPIC, "not-subscribed")
    with pytest.raises(KeyError):
        broker.ack(TOPIC, "not-subscribed", "r")
    with pytest.raises(KeyError):
        broker.stats("nope", G)


def test_basic_create_topic_and_subscribe_idempotent(broker):
    broker.publish(TOPIC, "keep")
    broker.create_topic(TOPIC)
    broker.subscribe(TOPIC, G)
    assert payloads(broker.poll(TOPIC, G)) == ["keep"]


def test_fanout_every_group_gets_a_copy(broker):
    broker.subscribe(TOPIC, "inventory")
    broker.subscribe(TOPIC, "points")
    mid = broker.publish(TOPIC, "x")
    for g in (G, "inventory", "points"):
        [m] = broker.poll(TOPIC, g)
        assert m.message_id == mid
        assert m.payload == "x"


def test_fanout_late_subscriber_sees_only_new(broker):
    broker.publish(TOPIC, "old")
    broker.subscribe(TOPIC, "late")
    broker.publish(TOPIC, "new")
    assert payloads(broker.poll(TOPIC, "late", 10)) == ["new"]


def test_fanout_publish_without_subscribers(broker):
    broker.create_topic("empty")
    assert broker.publish("empty", 1)  # 没人订阅，也要返回 message_id


def test_group_competing_consumers_get_different_messages(broker):
    broker.publish(TOPIC, "a")
    broker.publish(TOPIC, "b")
    [m1] = broker.poll(TOPIC, G)  # 消费者 1
    [m2] = broker.poll(TOPIC, G)  # 消费者 2
    assert {m1.payload, m2.payload} == {"a", "b"}


def test_group_groups_are_independent(broker, clock):
    broker.subscribe(TOPIC, "other")
    broker.publish(TOPIC, "x")
    [a] = broker.poll(TOPIC, G)
    [b] = broker.poll(TOPIC, "other")
    assert broker.ack(TOPIC, G, a.receipt)
    assert broker.ack(TOPIC, "other", a.receipt) is False, "回执只在自己的组里有效"
    clock.advance(11)
    assert broker.poll(TOPIC, G) == []
    assert payloads(broker.poll(TOPIC, "other")) == ["x"]  # other 组没 ack，超时重投


# =====================================================================
# ack / 可见性超时 / nack / extend
# =====================================================================


def test_ack_twice_and_bogus_receipt(broker):
    broker.publish(TOPIC, 1)
    [m] = broker.poll(TOPIC, G)
    assert broker.ack(TOPIC, G, "bogus") is False
    assert broker.ack(TOPIC, G, m.receipt) is True
    assert broker.ack(TOPIC, G, m.receipt) is False


def test_ack_in_flight_invisible_until_timeout(broker, clock):
    broker.publish(TOPIC, "job")
    [m] = broker.poll(TOPIC, G)
    clock.advance(9.99)
    assert broker.poll(TOPIC, G) == []
    clock.advance(0.01)  # 正好到截止时间：算超时
    [again] = broker.poll(TOPIC, G)
    assert again.message_id == m.message_id
    assert again.delivery_count == 2
    assert again.receipt != m.receipt


def test_ack_at_deadline_is_too_late(broker, clock):
    broker.publish(TOPIC, "job")
    [m] = broker.poll(TOPIC, G)
    clock.advance(10)
    assert broker.ack(TOPIC, G, m.receipt) is False


def test_ack_stale_receipt_cannot_ack_redelivery(broker, clock):
    broker.publish(TOPIC, "job")
    [first] = broker.poll(TOPIC, G)
    clock.advance(10)
    [second] = broker.poll(TOPIC, G)
    assert broker.ack(TOPIC, G, first.receipt) is False, "超时的旧回执不能 ack 已经重投出去的消息"
    assert broker.ack(TOPIC, G, second.receipt) is True


def test_ack_redelivered_message_comes_before_newer(broker, clock):
    broker.publish(TOPIC, "old")
    broker.poll(TOPIC, G)
    clock.advance(5)
    broker.publish(TOPIC, "new")
    clock.advance(5)
    assert payloads(broker.poll(TOPIC, G, 10)) == ["old", "new"]


def test_ack_out_of_order(broker):
    for i in range(3):
        broker.publish(TOPIC, i)
    ms = broker.poll(TOPIC, G, 3)
    assert broker.ack(TOPIC, G, ms[2].receipt)
    assert broker.ack(TOPIC, G, ms[0].receipt)
    assert broker.stats(TOPIC, G) == {"ready": 0, "in_flight": 1, "delayed": 0, "dead": 0}


def test_nack_immediate_redelivery(broker):
    broker.publish(TOPIC, "job")
    [m] = broker.poll(TOPIC, G)
    assert broker.nack(TOPIC, G, m.receipt) is True
    [again] = broker.poll(TOPIC, G)
    assert again.delivery_count == 2
    assert broker.nack(TOPIC, G, m.receipt) is False  # 旧回执已失效


def test_nack_with_delay(broker, clock):
    broker.publish(TOPIC, "job")
    [m] = broker.poll(TOPIC, G)
    assert broker.nack(TOPIC, G, m.receipt, delay=30)
    clock.advance(29.9)
    assert broker.poll(TOPIC, G) == []
    assert broker.stats(TOPIC, G)["delayed"] == 1
    clock.advance(0.1)
    assert payloads(broker.poll(TOPIC, G)) == ["job"]


def test_nack_negative_delay(broker):
    broker.publish(TOPIC, "job")
    [m] = broker.poll(TOPIC, G)
    with pytest.raises(ValueError):
        broker.nack(TOPIC, G, m.receipt, delay=-1)


def test_extend_keeps_message_invisible(broker, clock):
    broker.publish(TOPIC, "long-job")
    [m] = broker.poll(TOPIC, G)
    clock.advance(8)
    assert broker.extend(TOPIC, G, m.receipt, 20) is True
    clock.advance(15)  # 已经过了原来的截止时间，但续期到了 28
    assert broker.poll(TOPIC, G) == []
    assert broker.ack(TOPIC, G, m.receipt) is True


def test_extend_after_expiry_fails(broker, clock):
    broker.publish(TOPIC, "job")
    [m] = broker.poll(TOPIC, G)
    clock.advance(10)
    assert broker.extend(TOPIC, G, m.receipt, 20) is False
    assert broker.extend(TOPIC, G, "bogus", 20) is False
    with pytest.raises(ValueError):
        broker.extend(TOPIC, G, m.receipt, 0)


# =====================================================================
# 死信
# =====================================================================


def test_dead_after_max_deliveries_by_timeout(broker, clock):
    mid = broker.publish(TOPIC, "poison")
    for n in (1, 2, 3):
        [m] = broker.poll(TOPIC, G)
        assert m.delivery_count == n
        clock.advance(10)
    assert broker.poll(TOPIC, G) == [], "投递 3 次都失败，应该进死信，不再投递"
    [d] = broker.dead_letters(TOPIC, G)
    assert (d.message_id, d.payload, d.delivery_count, d.receipt) == (mid, "poison", 3, None)


def test_dead_after_max_deliveries_by_nack(broker):
    broker.publish(TOPIC, "poison")
    for _ in range(3):
        [m] = broker.poll(TOPIC, G)
        broker.nack(TOPIC, G, m.receipt)
    assert broker.poll(TOPIC, G) == []
    assert len(broker.dead_letters(TOPIC, G)) == 1


def test_dead_letter_does_not_block_others(broker, clock):
    broker.publish(TOPIC, "poison")
    broker.publish(TOPIC, "ok")
    for _ in range(3):
        ms = broker.poll(TOPIC, G, 10)
        for m in ms:
            if m.payload == "poison":
                broker.nack(TOPIC, G, m.receipt)
            else:
                broker.ack(TOPIC, G, m.receipt)
    assert payloads(broker.dead_letters(TOPIC, G)) == ["poison"]
    assert broker.stats(TOPIC, G) == {"ready": 0, "in_flight": 0, "delayed": 0, "dead": 1}


def test_dead_letters_in_order_of_death():
    b = Broker(max_deliveries=1, clock=FakeClock())
    b.create_topic("t")
    b.subscribe("t", "g")
    b.publish("t", "first")
    b.publish("t", "second")
    m1, m2 = b.poll("t", "g", 2)
    b.nack("t", "g", m2.receipt)
    b.nack("t", "g", m1.receipt)
    assert payloads(b.dead_letters("t", "g")) == ["second", "first"]


def test_dead_max_deliveries_one(clock):
    b = Broker(ack_timeout=5, max_deliveries=1, clock=clock)
    b.create_topic("t")
    b.subscribe("t", "g")
    b.publish("t", "once")
    b.poll("t", "g")
    clock.advance(5)
    assert b.poll("t", "g") == []
    assert b.stats("t", "g")["dead"] == 1


def test_redrive(broker, clock):
    broker.publish(TOPIC, "poison")
    for _ in range(3):
        broker.poll(TOPIC, G)
        clock.advance(10)
    assert broker.redrive(TOPIC, G) == 1
    assert broker.dead_letters(TOPIC, G) == []
    [m] = broker.poll(TOPIC, G)
    assert m.payload == "poison"
    assert m.delivery_count == 1, "redrive 之后投递次数重新计算"
    assert broker.ack(TOPIC, G, m.receipt)
    assert broker.redrive(TOPIC, G) == 0


def test_stats_lifecycle(broker, clock):
    for i in range(4):
        broker.publish(TOPIC, i)
    assert broker.stats(TOPIC, G) == {"ready": 4, "in_flight": 0, "delayed": 0, "dead": 0}
    a, b, c = broker.poll(TOPIC, G, 3)
    broker.ack(TOPIC, G, a.receipt)
    broker.nack(TOPIC, G, b.receipt, delay=100)
    assert broker.stats(TOPIC, G) == {"ready": 1, "in_flight": 1, "delayed": 1, "dead": 0}
    clock.advance(10)  # c 超时，回到可见
    assert broker.stats(TOPIC, G) == {"ready": 2, "in_flight": 0, "delayed": 1, "dead": 0}


# =====================================================================
# 并发
# =====================================================================


def test_thread_producers_and_consumers_exactly_once():
    b = Broker(ack_timeout=60)
    b.create_topic("t")
    b.subscribe("t", "g")
    total = 2000
    seen, lock = [], threading.Lock()
    done = threading.Event()

    def produce(k):
        for i in range(500):
            b.publish("t", (k, i))

    def consume():
        while not done.is_set():
            for m in b.poll("t", "g", max_messages=7):
                with lock:
                    seen.append(m.payload)
                    if len(seen) >= total:
                        done.set()
                assert b.ack("t", "g", m.receipt)

    consumers = [threading.Thread(target=consume) for _ in range(4)]
    producers = [threading.Thread(target=produce, args=(k,)) for k in range(4)]
    for t in consumers + producers:
        t.start()
    for t in producers:
        t.join()
    done.wait(timeout=20)
    done.set()
    for t in consumers:
        t.join()
    assert len(seen) == total, "有消息被同组的两个消费者重复拿到，或者丢了"
    assert len(set(seen)) == total
    assert b.stats("t", "g") == {"ready": 0, "in_flight": 0, "delayed": 0, "dead": 0}
