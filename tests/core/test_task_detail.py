"""测试:任务详情与提醒记录查询(queries.task_detail / task_pushes)。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, queries

TODAY = datetime.now().date()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def test_detail_start_task(conn):
    tid = db.add_task(conn, "看朋友", "start", anchor=str(TODAY - timedelta(days=60)),
                      cycle_days=30, priority=4, created=str(TODAY), tags=("朋友",))
    d = queries.task_detail(tid, conn)
    assert d["id"] == tid
    assert d["title"] == "看朋友"
    assert d["drive"] == "start"
    assert d["tags"] == ["朋友"]
    assert d["days_since"] == 60
    assert d["importance"] > 0            # 超期 2 倍周期 → 正


def test_detail_end_task_has_countdown(conn):
    deadline = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    tid = db.add_task(conn, "交报告", "end", deadline=deadline, priority=5, created=str(TODAY), tags=("公司",))
    d = queries.task_detail(tid, conn)
    assert d["drive"] == "end"
    assert d["countdown"].startswith("还剩")
    assert "days_since" not in d          # end 任务不给 days_since


def test_detail_not_found(conn):
    assert queries.task_detail("不存在的id", conn) is None


def test_pushes_empty(conn):
    tid = db.add_task(conn, "体检", "start", anchor=str(TODAY), cycle_days=365, created=str(TODAY))
    assert queries.task_pushes(tid, conn) == []


def test_pushes_desc_order(conn):
    tid = db.add_task(conn, "体检", "start", anchor=str(TODAY), cycle_days=365, created=str(TODAY))
    db.log_push(conn, tid, "2026-07-20 09:00:00", "gentle")
    db.log_push(conn, tid, "2026-07-25 10:00:00", "escalating", response="snoozed")
    db.log_push(conn, tid, "2026-07-27 11:00:00", "crisis", response="done")
    pushes = queries.task_pushes(tid, conn)
    assert len(pushes) == 3
    # 倒序:最新在前
    assert pushes[0]["stage"] == "crisis"
    assert pushes[0]["response"] == "done"
    assert pushes[-1]["stage"] == "gentle"
