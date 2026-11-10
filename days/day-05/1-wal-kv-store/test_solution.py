import importlib.util
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day05_kv_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
encode_record = _mod.encode_record
decode_records = _mod.decode_records
KVStore = _mod.KVStore
OP_PUT, OP_DELETE = _mod.OP_PUT, _mod.OP_DELETE


def wal(path):
    return Path(path) / "wal.log"


def run_child(code, *args):
    """在子进程里跑一段代码，最后用 os._exit(0) 模拟进程被直接杀掉（不关文件、不跑清理）。"""
    prelude = (
        "import importlib.util, os, sys\n"
        "spec = importlib.util.spec_from_file_location('s', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
    )
    subprocess.run(
        [sys.executable, "-c", prelude + code + "\nos._exit(0)\n", str(_SOLUTION), *map(str, args)],
        check=True, capture_output=True, text=True,
    )


# =====================================================================
# 记录编解码
# =====================================================================


def test_record_exact_bytes():
    body = struct.pack(">BII", 1, 3, 5) + b"abc" + b"hello"
    expected = struct.pack(">I", zlib.crc32(body)) + body
    assert encode_record(OP_PUT, b"abc", b"hello") == expected


def test_record_delete_has_empty_value():
    rec = encode_record(OP_DELETE, b"k")
    assert len(rec) == 13 + 1
    assert struct.unpack(">IBII", rec[:13])[1:] == (2, 1, 0)


def test_record_invalid_op():
    with pytest.raises(ValueError):
        encode_record(3, b"k", b"v")


def test_record_roundtrip_many():
    recs = [(OP_PUT, f"k{i}".encode(), os.urandom(i)) for i in range(50)] + [(OP_DELETE, b"k7", b"")]
    data = b"".join(encode_record(*r) for r in recs)
    out, valid = decode_records(data)
    assert out == recs
    assert valid == len(data)


def test_record_decode_empty():
    assert decode_records(b"") == ([], 0)


@pytest.mark.parametrize("cut", [1, 5, 12, 13, 14, 20])
def test_record_decode_stops_at_torn_tail(cut):
    good = encode_record(OP_PUT, b"a", b"1") + encode_record(OP_PUT, b"b", b"2")
    torn = encode_record(OP_PUT, b"ccc", b"third-value")[:cut]
    out, valid = decode_records(good + torn)
    assert [k for _, k, _ in out] == [b"a", b"b"]
    assert valid == len(good)


def test_record_decode_stops_at_bad_crc_and_ignores_rest():
    recs = [encode_record(OP_PUT, f"k{i}".encode(), b"v" * 10) for i in range(4)]
    bad = bytearray(recs[1])
    bad[-1] ^= 0xFF  # value 的最后一个字节翻转
    data = recs[0] + bytes(bad) + recs[2] + recs[3]
    out, valid = decode_records(data)
    assert [k for _, k, _ in out] == [b"k0"]
    assert valid == len(recs[0])


def test_record_decode_stops_at_unknown_op():
    body = struct.pack(">BII", 9, 1, 1) + b"kv"
    data = encode_record(OP_PUT, b"a", b"1") + struct.pack(">I", zlib.crc32(body)) + body
    out, valid = decode_records(data)
    assert len(out) == 1


# =====================================================================
# 基本读写
# =====================================================================


def test_basic_put_get_delete(tmp_path):
    with KVStore(tmp_path / "db") as db:
        assert db.get("x") is None
        assert db.get("x", b"d") == b"d"
        db.put("x", b"1")
        db.put("y", b"2")
        db.put("x", b"3")
        assert db.get("x") == b"3"
        assert "y" in db and "z" not in db
        assert len(db) == 2
        assert db.keys() == ["x", "y"]
        assert db.delete("x") is True
        assert db.delete("x") is False
        assert db.keys() == ["y"]


def test_creates_directory(tmp_path):
    d = tmp_path / "a" / "b" / "c"
    KVStore(d).close()
    assert d.is_dir()


def test_type_checks(tmp_path):
    with KVStore(tmp_path) as db:
        with pytest.raises(TypeError):
            db.put("k", "not-bytes")
        with pytest.raises(TypeError):
            db.put(1, b"v")


def test_unicode_keys_and_binary_values(tmp_path):
    with KVStore(tmp_path) as db:
        db.put("用户:张三", bytes(range(256)))
    with KVStore(tmp_path) as db:
        assert db.get("用户:张三") == bytes(range(256))


def test_empty_value_is_a_value(tmp_path):
    with KVStore(tmp_path) as db:
        db.put("k", b"")
    with KVStore(tmp_path) as db:
        assert "k" in db
        assert db.get("k") == b""


def test_closed_store_raises(tmp_path):
    db = KVStore(tmp_path)
    db.close()
    for call in (lambda: db.put("k", b"v"), lambda: db.get("k"), lambda: db.delete("k")):
        with pytest.raises(ValueError):
            call()


# =====================================================================
# WAL 与恢复
# =====================================================================


def test_wal_contents_are_exact(tmp_path):
    with KVStore(tmp_path) as db:
        db.put("a", b"1")
        db.delete("a")
        db.delete("nope")  # 不存在的 key 不写日志
    expected = encode_record(OP_PUT, b"a", b"1") + encode_record(OP_DELETE, b"a")
    assert wal(tmp_path).read_bytes() == expected


def test_reopen_restores_state(tmp_path):
    with KVStore(tmp_path) as db:
        for i in range(100):
            db.put(f"k{i}", str(i).encode())
        for i in range(0, 100, 2):
            db.delete(f"k{i}")
        db.put("k1", b"updated")
    with KVStore(tmp_path) as db:
        assert len(db) == 50
        assert db.get("k1") == b"updated"
        assert db.get("k3") == b"3"
        assert "k2" not in db
        assert db.recovered_records == 151
        assert db.discarded_bytes == 0


def test_survives_hard_kill(tmp_path):
    run_child(
        "db = m.KVStore(sys.argv[2])\n"
        "for i in range(200): db.put(f'k{i}', b'v' * 100)\n",
        tmp_path,
    )
    with KVStore(tmp_path) as db:
        assert len(db) == 200, "进程被杀后数据丢了：put 返回前有没有 flush？"


def test_survives_hard_kill_with_sync_false(tmp_path):
    # sync=False 只是不 fsync，进程被杀（不是断电）时数据仍然应该在操作系统的页缓存里。
    run_child(
        "db = m.KVStore(sys.argv[2], sync=False)\n"
        "for i in range(50): db.put(f'k{i}', b'v')\n",
        tmp_path,
    )
    with KVStore(tmp_path) as db:
        assert len(db) == 50


def test_fsync_called_per_write_when_sync(tmp_path, monkeypatch):
    calls = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real(fd)))
    with KVStore(tmp_path, sync=True) as db:
        before = len(calls)
        for i in range(10):
            db.put(f"k{i}", b"v")
        db.delete("k0")
        assert len(calls) - before >= 11


def test_no_fsync_when_sync_false(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
    with KVStore(tmp_path, sync=False) as db:
        before = len(calls)
        for i in range(10):
            db.put(f"k{i}", b"v")
        assert len(calls) == before, "sync=False 时每次写不应该 fsync"


@pytest.mark.parametrize("cut", [3, 13, 20])
def test_recovery_discards_torn_tail_and_truncates(tmp_path, cut):
    with KVStore(tmp_path) as db:
        for i in range(3):
            db.put(f"k{i}", b"value")
    good_size = wal(tmp_path).stat().st_size
    torn = encode_record(OP_PUT, b"k3", b"half-written-value")[:cut]
    with open(wal(tmp_path), "ab") as f:
        f.write(torn)

    with KVStore(tmp_path) as db:
        assert db.keys() == ["k0", "k1", "k2"]
        assert db.recovered_records == 3
        assert db.discarded_bytes == cut
        assert wal(tmp_path).stat().st_size == good_size, "恢复后要把坏掉的尾巴截掉"
        db.put("k4", b"after-crash")

    with KVStore(tmp_path) as db:
        assert db.get("k4") == b"after-crash", "新记录写在了垃圾后面，再次恢复时读不到"
        assert db.discarded_bytes == 0


def test_recovery_stops_at_corruption_in_the_middle(tmp_path):
    with KVStore(tmp_path) as db:
        for i in range(4):
            db.put(f"k{i}", b"x" * 10)
    data = bytearray(wal(tmp_path).read_bytes())
    rec_len = len(encode_record(OP_PUT, b"k0", b"x" * 10))
    data[rec_len + 15] ^= 0x01  # 第 2 条记录里翻转一位
    wal(tmp_path).write_bytes(bytes(data))
    with KVStore(tmp_path) as db:
        assert db.keys() == ["k0"]
        assert db.discarded_bytes == 3 * rec_len


def test_recovery_of_empty_or_missing_wal(tmp_path):
    with KVStore(tmp_path) as db:
        assert len(db) == 0
        assert db.recovered_records == 0


# =====================================================================
# 快照（compaction）
# =====================================================================


def test_compact_writes_snapshot_and_truncates_wal(tmp_path):
    with KVStore(tmp_path) as db:
        for i in range(10):
            db.put("hot", str(i).encode())
        db.put("cold", b"c")
        db.put("gone", b"g")
        db.delete("gone")
        db.compact()
        assert wal(tmp_path).stat().st_size == 0
        snap, valid = decode_records((tmp_path / "snapshot.dat").read_bytes())
        assert sorted((k, v) for _, k, v in snap) == [(b"cold", b"c"), (b"hot", b"9")]
        assert all(op == OP_PUT for op, _, _ in snap)
        assert not (tmp_path / "snapshot.dat.tmp").exists()
        db.put("after", b"a")
    with KVStore(tmp_path) as db:
        assert db.keys() == ["after", "cold", "hot"]
        assert db.get("hot") == b"9"
        assert db.recovered_records == 1  # 只重放快照之后的那一条


def test_compact_uses_atomic_replace(tmp_path, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append((Path(a).name, Path(b).name)), real(a, b)))
    with KVStore(tmp_path) as db:
        db.put("k", b"v")
        db.compact()
    assert ("snapshot.dat.tmp", "snapshot.dat") in seen


def test_compact_crash_before_replace_leaves_tmp(tmp_path):
    with KVStore(tmp_path) as db:
        db.put("a", b"1")
        db.compact()
        db.put("b", b"2")
    # 模拟：第二次 compact 写 tmp 写到一半就断电，snapshot.dat 和 wal.log 都还是旧的
    (tmp_path / "snapshot.dat.tmp").write_bytes(encode_record(OP_PUT, b"zzz", b"garbage")[:9])
    with KVStore(tmp_path) as db:
        assert db.keys() == ["a", "b"]
        assert not (tmp_path / "snapshot.dat.tmp").exists()


def test_compact_crash_after_replace_before_truncate(tmp_path):
    with KVStore(tmp_path) as db:
        db.put("a", b"1")
        db.put("b", b"2")
        db.delete("a")
        db.put("c", b"3")
        db.put("b", b"22")
        old_wal = wal(tmp_path).read_bytes()
        db.compact()
    # 模拟：快照已经换好，但截断 WAL 之前断电，旧日志还在
    wal(tmp_path).write_bytes(old_wal)
    with KVStore(tmp_path) as db:
        assert db.keys() == ["b", "c"]
        assert db.get("b") == b"22"


def test_compact_threshold_bounds_wal_size(tmp_path):
    with KVStore(tmp_path, compact_threshold=4096) as db:
        for i in range(2000):
            db.put(f"k{i % 20}", os.urandom(50))
            assert wal(tmp_path).stat().st_size < 4096
        final = {k: db.get(k) for k in db.keys()}
    with KVStore(tmp_path) as db:
        assert len(db) == 20
        assert {k: db.get(k) for k in db.keys()} == final


def test_compact_threshold_none_never_compacts(tmp_path):
    with KVStore(tmp_path) as db:
        for i in range(500):
            db.put("k", b"v" * 100)
    assert not (tmp_path / "snapshot.dat").exists()


def test_compact_survives_hard_kill(tmp_path):
    run_child(
        "db = m.KVStore(sys.argv[2], compact_threshold=2000)\n"
        "for i in range(300): db.put(f'k{i % 30}', str(i).encode())\n",
        tmp_path,
    )
    with KVStore(tmp_path) as db:
        assert len(db) == 30
        assert db.get("k29") == b"299"
        assert db.get("k0") == b"270"
