"""测试:任务详情与提醒记录查询(queries.task_detail / task_pushes)。

内部存 Unix 秒 int;task_detail/task_pushes 出口转成字符串喂前端。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, queries
from assistant.core.timeutil import SECONDS_PER_DAY, to_str

DAY = SECONDS_PER_DAY
NOW = int(time.time())


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def test_detail_start_task(conn):
    tid = db.add_task(conn, "看朋友", "start", anchor=NOW - 60 * DAY,
                      cycle_days=30, priority=4, created=NOW, tags=("朋友",))
    d = queries.task_detail(tid, conn)
    assert d["id"] == tid
    assert d["title"] == "看朋友"
    assert d["drive"] == "start"
    assert d["tags"] == ["朋友"]
    assert d["days_since"] == pytest.approx(60.0)   # 按秒差算,浮点
    assert d["importance"] > 0                       # 超期 2 倍周期 → 正
    assert d["anchor"] == to_str(NOW - 60 * DAY)[:10]  # 出口转回 'YYYY-MM-DD'


def test_detail_end_task_has_countdown(conn):
    deadline = NOW + 2 * DAY
    tid = db.add_task(conn, "交报告", "end", deadline=deadline, priority=5,
                      created=NOW, tags=("公司",))
    d = queries.task_detail(tid, conn)
    assert d["drive"] == "end"
    assert d["countdown"].startswith("还剩")
    assert d["deadline"] == to_str(deadline)         # 出口转回 'YYYY-MM-DD HH:MM'
    assert "days_since" not in d                     # end 任务不给 days_since


def test_detail_created_is_string(conn):
    tid = db.add_task(conn, "体检", "start", anchor=NOW, cycle_days=365, created=NOW)
    d = queries.task_detail(tid, conn)
    assert d["created"] == to_str(NOW)


def test_detail_not_found(conn):
    assert queries.task_detail("不存在的id", conn) is None


def test_pushes_empty(conn):
    tid = db.add_task(conn, "体检", "start", anchor=NOW, cycle_days=365, created=NOW)
    assert queries.task_pushes(tid, conn) == []


def test_pushes_desc_order_and_string_time(conn):
    tid = db.add_task(conn, "体检", "start", anchor=NOW, cycle_days=365, created=NOW)
    db.log_push(conn, tid, NOW - 3 * DAY, "gentle")
    db.log_push(conn, tid, NOW - 2 * DAY, "escalating", response="snoozed")
    db.log_push(conn, tid, NOW - DAY, "crisis", response="done")
    pushes = queries.task_pushes(tid, conn)
    assert len(pushes) == 3
    # 倒序:最新在前
    assert pushes[0]["stage"] == "crisis"
    assert pushes[0]["response"] == "done"
    assert pushes[-1]["stage"] == "gentle"
    # pushed_at 出口转字符串
    assert pushes[0]["pushed_at"] == to_str(NOW - DAY)
