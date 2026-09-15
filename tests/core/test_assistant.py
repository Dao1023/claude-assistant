"""测试:数据库、任务动作、重要性算法、推送逻辑。用临时 DB,不碰正式数据。

时间与周期内部一律 Unix 秒级 int(core/timeutil.py)。
字段级拆分:start 用 anchor+expected_duration(秒)+is_cyclic;
end 用 deadline+recurrence_interval(秒,可空)。超时即关闭(actions.close_overdue)。
"""
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import actions, db, engine

DAY = 86400
NOW = int(time.time())


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """每个测试用独立临时 DB。db.connect() 动态读 config.DB_PATH。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


# ---------- 重要性算法(按秒) ----------

def test_start_x_eq_1_gives_zero():
    assert engine.start_importance(NOW - 30 * DAY, 30 * DAY, now=NOW) == 0


def test_start_x_gt_1_positive():
    assert engine.start_importance(NOW - 60 * DAY, 30 * DAY, now=NOW) > 0


def test_start_x_lt_1_negative():
    assert engine.start_importance(NOW - 15 * DAY, 30 * DAY, now=NOW) < 0


def test_start_same_moment_is_finite_negative_not_inf():
    v = engine.start_importance(NOW, 30 * DAY, now=NOW)
    assert v < 0 and v != float("-inf")


def test_start_result_json_serializable():
    for anchor in (NOW, NOW - DAY, NOW - 100 * DAY):
        v = engine.start_importance(anchor, 30 * DAY, now=NOW)
        json.dumps({"importance": v}, allow_nan=False)


def test_start_no_duration_gives_zero():
    # 一次性 start 没填预期间隔 → 无法归一化,返回 0
    assert engine.start_importance(NOW - 60 * DAY, None, now=NOW) == 0


def test_end_far_negative():
    assert engine.end_importance(NOW + 30 * DAY, now=NOW) < 0


def test_end_one_day_zero():
    assert engine.end_importance(NOW + DAY, now=NOW) == 0


def test_end_monotonic_nearer_is_bigger():
    assert engine.end_importance(NOW + 2 * DAY, now=NOW) > engine.end_importance(NOW + 30 * DAY, now=NOW)


def test_start_normalized_by_duration():
    # 长预期间隔不会像纯时长那样霸榜
    long_cycle = engine.start_importance(NOW - 200 * DAY, 365 * DAY, now=NOW)
    short_cycle = engine.start_importance(NOW - 60 * DAY, 30 * DAY, now=NOW)
    assert long_cycle < short_cycle


# ---------- 新增任务:字段级拆分 ----------

def test_add_start_uses_expected_duration(conn):
    r = actions.do_add(conn, {"title": "看发小", "drive": "start",
                               "expected_duration": 30 * DAY, "is_cyclic": 0})
    sched = conn.execute("SELECT * FROM schedule WHERE task_id=?", (r["task_id"],)).fetchone()
    assert sched["expected_duration"] == 30 * DAY
    assert sched["recurrence_interval"] is None          # start 不填 end 字段
    assert abs(sched["anchor"] - NOW) < 5                # 缺省锚点≈now


def test_add_end_uses_recurrence_interval(conn):
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end",
                               "deadline": NOW + 3600, "recurrence_interval": DAY})
    sched = conn.execute("SELECT * FROM schedule WHERE task_id=?", (r["task_id"],)).fetchone()
    assert sched["recurrence_interval"] == DAY
    assert sched["expected_duration"] is None            # end 不填 start 字段
    assert db.get_task(conn, r["task_id"])["is_cyclic"] == 0  # end 不用 is_cyclic


def test_add_does_not_auto_cyclic(conn):
    # 填了 expected_duration 不自动变周期(解耦:is_cyclic 独立)
    r = actions.do_add(conn, {"title": "论文", "drive": "start", "expected_duration": 15 * DAY})
    assert db.get_task(conn, r["task_id"])["is_cyclic"] == 0


# ---------- 完成:一次性 vs 周期 ----------

def test_done_oneoff_start_does_not_clone(conn):
    # 一次性 start(expected_duration 有,is_cyclic=0)done 不克隆
    r = actions.do_add(conn, {"title": "论文", "drive": "start",
                               "expected_duration": 15 * DAY, "is_cyclic": 0})
    before = len(db.list_active(conn, "start"))
    actions.do_done(conn, {"task_id": r["task_id"]})
    assert len(db.list_active(conn, "start")) == before - 1   # 没有新实例


def test_done_cyclic_start_clones_and_resets_anchor(conn):
    r = actions.do_add(conn, {"title": "看发小", "drive": "start", "is_cyclic": 1,
                               "expected_duration": 30 * DAY, "anchor": NOW - 60 * DAY})
    before = len(db.list_active(conn, "start"))
    actions.do_done(conn, {"task_id": r["task_id"]})
    after = db.list_active(conn, "start")
    assert len(after) == before                              # 克隆了一个
    assert abs(after[0]["anchor"] - NOW) < 5                 # 锚点重置为 now


def test_done_cyclic_end_clones_and_shifts_deadline(conn):
    deadline = NOW + 3600
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end",
                               "deadline": deadline, "recurrence_interval": DAY})
    before = len(db.list_active(conn, "end"))
    res = actions.do_done(conn, {"task_id": r["task_id"]})
    after = db.list_active(conn, "end")
    assert len(after) == before and res["cyclic"]
    assert after[0]["deadline"] == deadline + DAY            # 顺延,精确保留时分
    assert db.get_task(conn, r["task_id"])["status"] == "done"


def test_done_oneoff_end_does_not_clone(conn):
    r = actions.do_add(conn, {"title": "交报告", "drive": "end", "deadline": NOW + 3600})
    before = len(db.list_active(conn, "end"))
    actions.do_done(conn, {"task_id": r["task_id"]})
    assert len(db.list_active(conn, "end")) == before - 1


# ---------- 超时即关闭 ----------

def test_close_overdue_closes_expired_end(conn):
    r = actions.do_add(conn, {"title": "过了的活", "drive": "end", "deadline": NOW - 3600})
    n = actions.close_overdue(conn, now=NOW)
    assert n == 1
    assert db.get_task(conn, r["task_id"])["status"] == "closed"


def test_close_overdue_keeps_future_end(conn):
    r = actions.do_add(conn, {"title": "还没到", "drive": "end", "deadline": NOW + 3600})
    actions.close_overdue(conn, now=NOW)
    assert db.get_task(conn, r["task_id"])["status"] == "active"


def test_close_overdue_cyclic_clones_next(conn):
    # 周期任务超时:当前 closed + 克隆下一个
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end",
                               "deadline": NOW - 3600, "recurrence_interval": DAY})
    actions.close_overdue(conn, now=NOW)
    assert db.get_task(conn, r["task_id"])["status"] == "closed"
    active = db.list_active(conn, "end")
    assert len(active) == 1                                  # 克隆出下一个
    assert active[0]["deadline"] == NOW - 3600 + DAY


def test_close_overdue_cyclic_overdue_days_jumps_to_future(conn):
    # 停机多天场景:过期 10 天,一次 close_overdue 直接跳到第一个未来截止点
    # (方案 B:停机期间的日子不补记录),不靠后续轮次慢慢爬
    deadline = NOW - 10 * DAY - 3600
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end",
                               "deadline": deadline, "recurrence_interval": DAY})
    actions.close_overdue(conn, now=NOW)
    assert db.get_task(conn, r["task_id"])["status"] == "closed"
    active = db.list_active(conn, "end")
    assert len(active) == 1                                  # 只克隆出当前份
    assert active[0]["deadline"] == deadline + 11 * DAY      # 第一个未来点(now + DAY - 3600)
    assert active[0]["deadline"] > NOW


def test_close_overdue_cyclic_multi_day_no_intermediate_records(conn):
    # 追平不产生中间记录:停 10 天,任务总数只 +1(当前份),没有逐日爬升的垃圾
    actions.do_add(conn, {"title": "日语每日", "drive": "end",
                          "deadline": NOW - 10 * DAY, "recurrence_interval": DAY})
    before = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    actions.close_overdue(conn, now=NOW)
    after = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    assert after - before == 1


def test_close_overdue_cyclic_twice_does_not_duplicate(conn):
    # 连跑两遍不翻倍:第一遍已追平,第二遍无事发生(过期才处理)
    actions.do_add(conn, {"title": "异环每日", "drive": "end",
                          "deadline": NOW - 10 * DAY, "recurrence_interval": DAY})
    actions.close_overdue(conn, now=NOW)
    actions.close_overdue(conn, now=NOW)
    assert len(db.list_active(conn, "end")) == 1


def test_close_overdue_concurrent_connections_do_not_duplicate(conn):
    # 面板线程(/api/tasks)与调度线程(tick)同批处理同一过期任务:
    # 两个连接同时追平,原子认领下只有一方能克隆,链不翻倍。
    # 每个线程自建连接(sqlite3 连接默认不允许跨线程用)
    actions.do_add(conn, {"title": "原神每日", "drive": "end",
                          "deadline": NOW - 10 * DAY, "recurrence_interval": DAY})
    barrier = threading.Barrier(2)

    def run():
        c = db.connect()
        barrier.wait()
        try:
            actions.close_overdue(c, now=NOW)
        finally:
            c.close()

    workers = [threading.Thread(target=run) for _ in range(2)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    assert len(db.list_active(conn, "end")) == 1
    total = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    assert total == 2  # 原 1 条 + 克隆 1 条,不多不少


def test_close_overdue_ignores_start(conn):
    r = actions.do_add(conn, {"title": "看发小", "drive": "start",
                               "expected_duration": 30 * DAY, "anchor": NOW - 100 * DAY})
    n = actions.close_overdue(conn, now=NOW)
    assert n == 0
    assert db.get_task(conn, r["task_id"])["status"] == "active"   # start 不会因超时被关


# ---------- 推送统计 ----------

def test_push_stats(conn):
    r = actions.do_add(conn, {"title": "推送测试", "drive": "end", "deadline": NOW + DAY})
    tid = r["task_id"]
    db.log_push(conn, tid, NOW - 7200, "gentle")
    db.log_push(conn, tid, NOW - 3600, "escalating")
    n, last = db.push_stats(conn, tid)
    assert n == 2 and last == NOW - 3600


# ---------- 推迟选项按任务动态化(start=预期×系数,end=剩余×系数) ----------

def test_snooze_options_start_scales_by_expected():
    # start 预期 30 天 → ×0.1=3天 / ×0.5=15天 / ×1.0=30天
    t = {"drive": "start", "expected_duration": 30 * 86400}
    opts = actions.snooze_options(t)
    labels = [lbl for _, (lbl, _) in opts.items()]
    assert any("3 天" in l and "×0.1" in l for l in labels)
    assert any("15 天" in l and "×0.5" in l for l in labels)
    assert any("30 天" in l and "×1.0" in l for l in labels)


def test_snooze_options_end_scales_by_remaining():
    # end 剩 1 小时 → 最多 ×1.0=1小时(推迟超剩余就过期了)
    from assistant.core.timeutil import now_ts
    t = {"drive": "end", "deadline": now_ts() + 3600}
    opts = actions.snooze_options(t)
    untils = [u for _, (_, u) in opts.items()]
    now = now_ts()
    # 最大的推迟也不超过剩余 1 小时(容差 5 秒)
    assert max(untils) - now <= 3600 + 5


def test_snooze_options_fallback_without_task():
    opts = actions.snooze_options()
    assert "1h" in opts and "3h" in opts
