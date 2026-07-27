"""测试:数据库、指令、重要性算法、推送逻辑。用临时 DB,不碰正式数据。"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import commands, db, engine

TODAY = datetime.now().date()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """每个测试用独立临时 DB。db.connect() 动态读 config.DB_PATH。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


# ---------- 重要性算法 ----------

def test_start_x_eq_1_gives_zero():
    # x=1 → log(1)=0
    assert engine.start_importance(str(TODAY - timedelta(days=30)), 30) == 0


def test_start_x_gt_1_positive():
    # x=2 → log2>0
    assert engine.start_importance(str(TODAY - timedelta(days=60)), 30) > 0


def test_start_x_lt_1_negative():
    # x=0.5 → 负
    assert engine.start_importance(str(TODAY - timedelta(days=15)), 30) < 0


def test_start_same_day_is_neg_inf():
    # 当天 → x=0 → -inf
    assert engine.start_importance(str(TODAY), 30) == float("-inf")


def test_end_far_negative():
    # 剩30天 → -log30<0
    assert engine.end_importance(str(TODAY + timedelta(days=30))) < 0


def test_end_one_day_zero():
    # 剩1天 → 0
    assert engine.end_importance(str(TODAY + timedelta(days=1))) == 0


def test_end_overdue():
    # 已过期 → OVERDUE
    assert engine.end_importance(str(TODAY - timedelta(days=1))) == engine.OVERDUE


def test_end_monotonic_nearer_is_bigger():
    i_far = engine.end_importance(str(TODAY + timedelta(days=30)))
    i_near = engine.end_importance(str(TODAY + timedelta(days=2)))
    assert i_near > i_far


def test_start_older_is_bigger():
    s1 = engine.start_importance(str(TODAY - timedelta(days=30)), 30)
    s2 = engine.start_importance(str(TODAY - timedelta(days=300)), 30)
    assert s2 > s1


def test_start_normalized_by_cycle():
    # 体检200天(x<1) < 看朋友60天(x=2):长周期不会像纯时长那样霸榜
    ti_jian = engine.start_importance(str(TODAY - timedelta(days=200)), 365)
    friend = engine.start_importance(str(TODAY - timedelta(days=60)), 30)
    assert ti_jian < friend


# ---------- 数据库 + 指令 ----------

def test_add_end_cyclic_task(conn):
    r = commands.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": str(TODAY) + " 23:59",
                               "tags": ["genshin"]})
    assert "task_id" in r
    assert db.get_task(conn, r["task_id"])["title"] == "原神每日"


def test_add_task_tag_association(conn):
    r = commands.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": str(TODAY) + " 23:59",
                               "tags": ["genshin"]})
    tid = r["task_id"]
    tags = [x["name"] for x in conn.execute(
        "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id WHERE tt.task_id=?",
        (tid,))]
    assert "genshin" in tags


def test_done_cyclic_end_task_clones(conn):
    r = commands.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                               "cycle_days": 1, "deadline": str(TODAY) + " 23:59",
                               "tags": ["genshin"]})
    tid = r["task_id"]
    before = len(db.list_active(conn, "end"))
    r = commands.do_done(conn, {"task_id": tid})
    after = len(db.list_active(conn, "end"))
    assert after == before and r["cyclic"]
    assert db.get_task(conn, tid)["status"] == "done"


def test_done_cyclic_start_task_resets_anchor(conn):
    r = commands.do_add(conn, {"title": "看发小", "drive": "start", "is_cyclic": 1,
                               "cycle_days": 30, "anchor": "2026-06-01"})
    commands.do_done(conn, {"task_id": r["task_id"]})
    new = db.list_active(conn, "start")[0]
    assert new["anchor"] == str(TODAY)


def test_query_filters_by_tag(conn):
    commands.do_add(conn, {"title": "任务A", "drive": "end",
                           "deadline": str(TODAY), "tags": ["公司"]})
    commands.do_add(conn, {"title": "任务B", "drive": "end",
                           "deadline": str(TODAY), "tags": ["genshin"]})
    q = commands.do_query(conn, {"tag": "genshin"})
    assert len(q["tasks"]) == 1 and q["tasks"][0]["title"] == "任务B"


# ---------- 指令文件处理 ----------

def test_process_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    commands_file = tmp_path / "commands.json"
    monkeypatch.setattr(config, "COMMANDS", commands_file)
    commands_file.write_text(
        '{"commands": [{"id":"c1","action":"add","status":"pending",'
        '"payload":{"title":"测试任务","drive":"end","deadline":"%s"}}]}'
        % (str(TODAY) + " 18:00"),
        encoding="utf-8")
    n = commands.process_commands()
    assert n == 1
    data = json.loads(commands_file.read_text(encoding="utf-8"))
    assert data["commands"][0]["status"] == "processed"
    assert "task_id" in data["commands"][0]["result"]


# ---------- 推送统计 ----------

def test_push_stats(conn):
    r = commands.do_add(conn, {"title": "推送测试", "drive": "end", "deadline": str(TODAY)})
    tid = r["task_id"]
    db.log_push(conn, tid, "2026-07-27 10:00", "gentle")
    db.log_push(conn, tid, "2026-07-27 12:00", "escalating")
    n, last = db.push_stats(conn, tid)
    assert n == 2
    assert last == "2026-07-27 12:00"
