"""测试:数据库、任务动作、重要性算法、推送逻辑。用临时 DB,不碰正式数据。

时间与周期内部一律 Unix 秒级 int(core/timeutil.py),公式按秒算。
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import actions, db, engine
from assistant.core.timeutil import SECONDS_PER_DAY, now_ts

DAY = SECONDS_PER_DAY
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
    # 恰好一个周期 → x=1 → log(1)=0
    assert engine.start_importance(NOW - 30 * DAY, 30, now=NOW) == 0


def test_start_x_gt_1_positive():
    # 两个周期 → x=2 → log2>0
    assert engine.start_importance(NOW - 60 * DAY, 30, now=NOW) > 0


def test_start_x_lt_1_negative():
    # 半个周期 → x=0.5 → 负
    assert engine.start_importance(NOW - 15 * DAY, 30, now=NOW) < 0


def test_start_same_moment_is_finite_negative_not_inf():
    # anchor 恰等于 now → x=0 → 钳到下限,有限负数,不是 -inf
    v = engine.start_importance(NOW, 30, now=NOW)
    assert v < 0 and v != float("-inf")


def test_start_result_json_serializable():
    # 回归:任何 importance 都不能崩 JSON(allow_nan=False)
    for anchor in (NOW, NOW - DAY, NOW - 100 * DAY):
        v = engine.start_importance(anchor, 30, now=NOW)
        json.dumps({"importance": v}, allow_nan=False)


def test_end_far_negative():
    # 剩30天 → -log30<0
    assert engine.end_importance(NOW + 30 * DAY, now=NOW) < 0


def test_end_one_day_zero():
    # 剩1天 → 0
    assert engine.end_importance(NOW + DAY, now=NOW) == 0


def test_end_overdue():
    # 已过期 → OVERDUE
    assert engine.end_importance(NOW - DAY, now=NOW) == engine.OVERDUE


def test_end_monotonic_nearer_is_bigger():
    i_far = engine.end_importance(NOW + 30 * DAY, now=NOW)
    i_near = engine.end_importance(NOW + 2 * DAY, now=NOW)
    assert i_near > i_far


def test_start_older_is_bigger():
    s1 = engine.start_importance(NOW - 30 * DAY, 30, now=NOW)
    s2 = engine.start_importance(NOW - 300 * DAY, 30, now=NOW)
    assert s2 > s1


def test_start_normalized_by_cycle():
    # 体检200天(x<1) < 看朋友60天(x=2):长周期不会像纯时长那样霸榜
    ti_jian = engine.start_importance(NOW - 200 * DAY, 365, now=NOW)
    friend = engine.start_importance(NOW - 60 * DAY, 30, now=NOW)
    assert ti_jian < friend


# ---------- 数据库 + 指令 ----------

def test_add_end_cyclic_task(conn):
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": NOW + 3600,
                               "tags": ["genshin"]})
    assert "task_id" in r
    assert db.get_task(conn, r["task_id"])["title"] == "原神每日"


def test_add_start_task_defaults_anchor_to_now(conn):
    r = actions.do_add(conn, {"title": "看发小", "drive": "start", "cycle_days": 30})
    sched = conn.execute("SELECT anchor FROM schedule WHERE task_id=?",
                         (r["task_id"],)).fetchone()
    assert abs(sched["anchor"] - now_ts()) < 5      # 缺省锚点≈当前秒


def test_add_task_tag_association(conn):
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": NOW + 3600,
                               "tags": ["genshin"]})
    tid = r["task_id"]
    tags = [x["name"] for x in conn.execute(
        "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id WHERE tt.task_id=?",
        (tid,))]
    assert "genshin" in tags


def test_done_cyclic_end_task_clones(conn):
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": NOW + 3600,
                               "tags": ["genshin"]})
    tid = r["task_id"]
    before = len(db.list_active(conn, "end"))
    r = actions.do_done(conn, {"task_id": tid})
    after = len(db.list_active(conn, "end"))
    assert after == before and r["cyclic"]
    assert db.get_task(conn, tid)["status"] == "done"


def test_done_cyclic_end_keeps_time_of_day(conn):
    # 周期克隆按秒顺延:deadline 精确 +cycle 天,时分(如次日 4:00)不变
    deadline = NOW + 3600
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": deadline})
    actions.do_done(conn, {"task_id": r["task_id"]})
    new = db.list_active(conn, "end")[0]
    assert new["deadline"] == deadline + DAY


def test_done_cyclic_start_task_resets_anchor(conn):
    r = actions.do_add(conn, {"title": "看发小", "drive": "start", "is_cyclic": 1,
                               "cycle_days": 30, "anchor": NOW - 60 * DAY})
    actions.do_done(conn, {"task_id": r["task_id"]})
    new = db.list_active(conn, "start")[0]
    assert abs(new["anchor"] - now_ts()) < 5        # 锚点重置为现在


def test_query_filters_by_tag(conn):
    actions.do_add(conn, {"title": "任务A", "drive": "end",
                           "deadline": NOW + DAY, "tags": ["公司"]})
    actions.do_add(conn, {"title": "任务B", "drive": "end",
                           "deadline": NOW + DAY, "tags": ["genshin"]})
    q = actions.do_query(conn, {"tag": "genshin"})
    assert len(q["tasks"]) == 1 and q["tasks"][0]["title"] == "任务B"


# ---------- 推送统计 ----------

def test_push_stats(conn):
    r = actions.do_add(conn, {"title": "推送测试", "drive": "end", "deadline": NOW + DAY})
    tid = r["task_id"]
    db.log_push(conn, tid, NOW - 7200, "gentle")
    db.log_push(conn, tid, NOW - 3600, "escalating")
    n, last = db.push_stats(conn, tid)
    assert n == 2
    assert last == NOW - 3600
