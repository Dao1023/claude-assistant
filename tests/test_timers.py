"""计时器引擎测试:纯确定性逻辑,不碰真库、不碰意识层。

时间线统一用假时间戳(T0 起步),last_review 初始化为 T0,
这样本体回顾的 600s 节拍完全受测试控制。
"""
import pytest

from assistant.timers import TimerEngine

T0 = 1_000_000  # 假时间起点


@pytest.fixture()
def eng(tmp_path):
    e = TimerEngine(path=tmp_path / "timers.json", review_every=600)
    e._state["meta"]["last_review"] = T0
    return e


def test_once_fires_then_gone(eng):
    tid = eng.add("once", in_sec=60, label="交材料", payload="17:00 截止", now=T0)
    assert eng.due_batch(now=T0 + 59, awake=True) is None        # 没到点
    batch = eng.due_batch(now=T0 + 60, awake=True)
    assert batch["reason"] == "timers" and batch["count"] == 1
    assert "交材料" in batch["message"]
    assert all(t["id"] != tid for t in eng.list())               # once 出列
    assert eng.due_batch(now=T0 + 61, awake=True) is None


def test_interval_advances_skipping_missed_cycles(eng):
    eng.add("interval", every=100, label="日语", payload="该学了", now=T0)
    batch = eng.due_batch(now=T0 + 100, awake=True)
    assert batch["count"] == 1
    # 睡了 350:错过 3 个周期,醒来只触发一次(顺延到未来),不补发历史
    batch = eng.due_batch(now=T0 + 450, awake=True)
    assert batch["count"] == 1 and "日语" in batch["message"]
    t = eng.list()[0]
    assert t["fire_at"] > T0 + 450                                # 已顺延
    assert eng.due_batch(now=t["fire_at"] - 1) is None
    assert eng.due_batch(now=t["fire_at"])["count"] == 1


def test_sleep_saves_records_no_wake(eng):
    eng.add("once", in_sec=60, label="吃药", payload="该吃药了", now=T0)
    assert eng.due_batch(now=T0 + 100, awake=False) is None      # 睡眠:不唤醒
    assert len(eng.missed) == 1 and eng.missed[0]["label"] == "吃药"
    assert eng.due_batch(now=T0 + 101, awake=False) is None      # 记录不重复


def test_wakeup_returns_missed_first(eng):
    eng.add("once", in_sec=60, label="吃药", payload="该吃药了", now=T0)
    eng.due_batch(now=T0 + 100, awake=False)
    # 醒来:第一批是补课,优先于一切
    eng.add("once", at=T0 + 100, label="新任务", payload="刚到点", now=T0 + 100)
    batch = eng.due_batch(now=T0 + 102, awake=True)
    assert batch["reason"] == "missed" and "吃药" in batch["message"]
    assert eng.missed == []
    # 补课发完,下一批才是到点的自定义计时器
    batch = eng.due_batch(now=T0 + 102, awake=True)
    assert batch["reason"] == "timers" and "新任务" in batch["message"]


def test_conflict_merge_single_batch(eng):
    """多个计时器同刻到点 → 合并成一次唤醒(冲突自解/去抖)。"""
    eng.add("once", at=T0 + 600, label="A", payload="a", now=T0)
    eng.add("once", at=T0 + 600, label="B", payload="b", now=T0)
    eng.add("interval", at=T0 + 600, every=9999, label="C", payload="c", now=T0)
    batch = eng.due_batch(now=T0 + 600, awake=True)
    assert batch["count"] == 3
    assert all(x in batch["message"] for x in ("A", "B", "C"))
    assert len(eng.list()) == 1                                   # 只剩 interval


def test_review_tick(eng):
    assert eng.due_batch(now=T0 + 599, awake=True) is None       # 间隔内
    batch = eng.due_batch(now=T0 + 600, awake=True)
    assert batch["reason"] == "review"
    assert eng.due_batch(now=T0 + 650, awake=True) is None       # 新间隔内


def test_review_suppressed_when_sleeping(eng):
    assert eng.due_batch(now=T0 + 10_000, awake=False) is None   # 睡眠:不回顾


def test_reset_for_jump(eng):
    tid = eng.add("interval", every=100, label="专注", payload="休息一下", now=T0)
    eng.due_batch(now=T0 + 100, awake=True)
    assert eng.reset(tid, in_sec=1800, now=T0 + 100) is True     # 跳跃:大脑重设
    assert eng.list()[0]["fire_at"] == T0 + 100 + 1800
    assert eng.reset("t-nope", in_sec=1, now=T0) is False


def test_persistence_roundtrip(tmp_path):
    p = tmp_path / "timers.json"
    e1 = TimerEngine(path=p)
    e1.add("once", in_sec=60, label="x", payload="y", now=T0)
    e2 = TimerEngine(path=p)
    assert len(e2.list()) == 1 and e2.list()[0]["label"] == "x"


def test_bad_args(eng):
    with pytest.raises(ValueError):
        eng.add("jump", now=T0)                                   # 非法 kind
    with pytest.raises(ValueError):
        eng.add("once", label="x", now=T0)                        # 缺 at/in_sec
    with pytest.raises(ValueError):
        eng.add("interval", in_sec=10, label="x", now=T0)         # 缺 every
