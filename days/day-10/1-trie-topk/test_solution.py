import importlib.util
import random
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

_SOLUTION = Path(__file__).with_name("solution.py")
_spec = importlib.util.spec_from_file_location("day10_trie_solution", _SOLUTION)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
normalize_query = _mod.normalize_query
normalize_prefix = _mod.normalize_prefix
AutocompleteTrie = _mod.AutocompleteTrie
streaming_top_k = _mod.streaming_top_k


def brute_suggest(counts, prefix, k):
    items = [(q, c) for q, c in counts.items() if c > 0 and q.startswith(prefix)]
    items.sort(key=lambda t: (-t[1], t[0]))
    return [q for q, _ in items[:k]]


@pytest.fixture
def t():
    t = AutocompleteTrie(k=3)
    t.add("netflix", 50)
    t.add("news", 30)
    t.add("new york weather", 30)
    t.add("nba", 10)
    return t


# =====================================================================
# 规范化
# =====================================================================


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Netflix", "netflix"),
        ("  New   York\tWeather \n", "new york weather"),
        ("a", "a"),
        ("北京 天气", "北京 天气"),
    ],
)
def test_normalize_query(raw, expected):
    assert normalize_query(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_normalize_query_empty(raw):
    with pytest.raises(ValueError):
        normalize_query(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [("  New  ", "new "), ("NE", "ne"), ("", ""), ("   ", ""), ("new\t\tyo", "new yo")],
)
def test_normalize_prefix(raw, expected):
    assert normalize_prefix(raw) == expected


def test_normalize_type_errors():
    with pytest.raises(TypeError):
        normalize_query(123)
    with pytest.raises(TypeError):
        normalize_prefix(None)


# =====================================================================
# Trie：增加与联想
# =====================================================================


def test_trie_suggest_basic(t):
    assert t.suggest("ne") == ["netflix", "new york weather", "news"]
    assert t.suggest("n") == ["netflix", "new york weather", "news"]
    assert t.suggest("nb") == ["nba"]
    assert t.suggest("new ") == ["new york weather"]
    assert t.suggest("x") == []


def test_trie_suggest_limit(t):
    assert t.suggest("N", limit=1) == ["netflix"]
    with pytest.raises(ValueError):
        t.suggest("n", limit=4)
    with pytest.raises(ValueError):
        t.suggest("n", limit=0)


def test_trie_empty_prefix_is_global_top(t):
    t.add("apple", 40)
    assert t.suggest("") == ["netflix", "apple", "new york weather"]


def test_trie_add_normalizes_and_accumulates(t):
    t.add("  NBA ", 25)
    assert t.frequency("nba") == 35
    assert t.suggest("n") == ["netflix", "nba", "new york weather"]


def test_trie_tie_break_lexicographic():
    t = AutocompleteTrie(k=2)
    for q in ["cc", "ca", "cb"]:
        t.add(q, 7)
    assert t.suggest("c") == ["ca", "cb"]


def test_trie_word_that_is_prefix_of_another():
    t = AutocompleteTrie(k=5)
    t.add("new", 5)
    t.add("news", 3)
    t.add("ne", 1)
    assert t.suggest("ne") == ["new", "news", "ne"]
    assert t.suggest("new") == ["new", "news"]
    assert t.suggest("news") == ["news"]


def test_trie_rising_query_enters_cache():
    t = AutocompleteTrie(k=2)
    t.add("aa", 10)
    t.add("ab", 9)
    t.add("ac", 1)
    assert t.suggest("a") == ["aa", "ab"]
    for _ in range(9):
        t.add("ac")
    assert t.suggest("a") == ["aa", "ac"]


def test_trie_invalid_count(t):
    for bad in (0, -1, 1.5):
        with pytest.raises(ValueError):
            t.add("x", bad)


def test_trie_invalid_k():
    with pytest.raises(ValueError):
        AutocompleteTrie(k=0)


def test_trie_len_contains_frequency(t):
    assert len(t) == 4
    assert "NEWS" in t
    assert "new" not in t
    assert t.frequency("new") == 0
    assert t.frequency("missing") == 0


def test_trie_unicode():
    t = AutocompleteTrie(k=3)
    t.add("北京天气", 5)
    t.add("北京时间", 9)
    t.add("北海", 1)
    assert t.suggest("北京") == ["北京时间", "北京天气"]
    assert t.suggest("北") == ["北京时间", "北京天气", "北海"]


def test_trie_random_against_brute_force():
    rnd = random.Random(10)
    t = AutocompleteTrie(k=4)
    counts = {}
    alphabet = "abc "
    for _ in range(3000):
        q = normalize_query("".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 5))) + "x")
        c = rnd.randint(1, 5)
        t.add(q, c)
        counts[q] = counts.get(q, 0) + c
    for p in ["", "a", "b", "ab", "a ", "ca", "abc", "x", "cc c"]:
        assert t.suggest(p) == brute_suggest(counts, p, 4), p


# =====================================================================
# Trie：删除
# =====================================================================


def test_remove_basic(t):
    assert t.remove("Netflix") is True
    assert t.remove("netflix") is False
    assert "netflix" not in t
    assert len(t) == 3
    assert t.suggest("n") == ["new york weather", "news", "nba"], "删除后要从子树里补上新的 Top-K"


def test_remove_missing_and_prefix_only(t):
    assert t.remove("ne") is False  # 只是路径上的节点，不是一个词
    assert t.remove("zzz") is False
    assert len(t) == 4


def test_remove_then_add_again(t):
    t.remove("nba")
    t.add("nba", 2)
    assert t.frequency("nba") == 2
    assert t.suggest("nb") == ["nba"]


def test_remove_keeps_longer_words():
    t = AutocompleteTrie(k=3)
    t.add("new", 9)
    t.add("news", 3)
    t.remove("new")
    assert t.suggest("new") == ["news"]
    assert t.suggest("ne") == ["news"]


def test_remove_random_against_brute_force():
    rnd = random.Random(7)
    t = AutocompleteTrie(k=3)
    counts = {}
    words = ["".join(rnd.choice("abcd") for _ in range(rnd.randint(1, 4))) for _ in range(300)]
    for step in range(4000):
        w = rnd.choice(words)
        if rnd.random() < 0.15:
            assert t.remove(w) == (counts.get(w, 0) > 0)
            counts[w] = 0
        else:
            c = rnd.randint(1, 4)
            t.add(w, c)
            counts[w] = counts.get(w, 0) + c
        if step % 200 == 0:
            for p in ["", "a", "b", "ab", "dc", "abc"]:
                assert t.suggest(p) == brute_suggest(counts, p, 3), (step, p)
    assert len(t) == sum(1 for c in counts.values() if c > 0)


# =====================================================================
# Trie：性能（必须读缓存，不能遍历子树）
# =====================================================================


def test_perf_suggest_uses_cache():
    t = AutocompleteTrie(k=10)
    for i in range(100_000):
        t.add(f"a{i}", i % 997 + 1)
    start = time.perf_counter()
    for _ in range(3000):
        res = t.suggest("a")
    elapsed = time.perf_counter() - start
    assert len(res) == 10
    assert elapsed < 1.0, f"3000 次 suggest 用了 {elapsed:.2f}s，是不是每次都在遍历子树？"


# =====================================================================
# 流式 Top-K
# =====================================================================


def test_stream_basic():
    assert streaming_top_k(iter([("a", 3), ("b", 5), ("c", 3)]), 2) == [("b", 5), ("a", 3)]


def test_stream_fewer_than_k():
    assert streaming_top_k([("x", 1), ("y", 2)], 5) == [("y", 2), ("x", 1)]
    assert streaming_top_k([], 3) == []


def test_stream_invalid_k():
    with pytest.raises(ValueError):
        streaming_top_k([("a", 1)], 0)


def test_stream_ties_keep_smallest_strings():
    pairs = [(w, 1) for w in ["e", "b", "d", "a", "c"]]
    assert streaming_top_k(iter(pairs), 3) == [("a", 1), ("b", 1), ("c", 1)]


def test_stream_random_against_sorted():
    rnd = random.Random(3)
    pairs = [(f"w{i}", rnd.randint(1, 50)) for i in range(5000)]
    expected = sorted(pairs, key=lambda t: (-t[1], t[0]))[:100]
    assert streaming_top_k(iter(pairs), 100) == expected


def test_stream_single_pass_generator():
    consumed = []

    def gen():
        for i in range(1000):
            consumed.append(i)
            yield (f"q{i}", i)

    out = streaming_top_k(gen(), 3)
    assert out == [("q999", 999), ("q998", 998), ("q997", 997)]
    assert len(consumed) == 1000


def test_stream_bounded_memory():
    def gen():
        for i in range(1_000_000):
            yield (f"query-{i:07d}", (i * 7919) % 100_003)

    tracemalloc.start()
    out = streaming_top_k(gen(), 10)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(out) == 10
    assert out[0][1] == 100_002
    assert peak < 2_000_000, f"峰值内存 {peak / 1e6:.1f} MB，是不是把整个输入存下来了？"
