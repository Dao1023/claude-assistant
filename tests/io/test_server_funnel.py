"""测试:通知漏斗接口 GET /api/funnel。用临时 DB + TestClient。"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import actions, db, settings
from assistant.io.server import create_app

DAY = 86400
NOW = int(time.time())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)
    db.init_db()
    c = db.connect()
    db.set_setting(c, "dnd_night_end", 0)   # 关夜间窗口,漏斗统计不依赖跑测试的钟点
    db.set_setting(c, "dnd_until", "")
    c.close()
    yield TestClient(create_app())
    monkeypatch.setattr(settings, "_cache", None)


def _add(conn, title, drive, **kw):
    return actions.do_add(conn, {"title": title, "drive": drive, **kw})


def test_funnel_returns_layers_and_settings(client):
    r = client.get("/api/funnel")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    ids = [l["id"] for l in body["layers"]]
    assert ids == ["dnd", "future_period", "snooze", "limit", "stage"]
    # 免打扰层挂了夜间恢复点配置
    dnd = next(l for l in body["layers"] if l["id"] == "dnd")
    assert {s["key"] for s in dnd["settings"]} == {"dnd_night_end"}
    # 节流层挂限量 + 推送间隔两个配置
    limit = next(l for l in body["layers"] if l["id"] == "limit")
    assert {s["key"] for s in limit["settings"]} == {"max_concurrent", "poll_interval"}
    assert "poll_interval" in body
    assert "dnd" in body and body["dnd"]["active"] is False


def test_funnel_counts_blocked_tasks(client):
    conn = db.connect()
    # 一个「明天的每日」→ 应被 future_period 层挡 1 个
    _add(conn, "明日原神", "end", deadline=NOW + int(1.5 * DAY), recurrence_interval=DAY)
    # 一个被推迟的任务 → snooze 层挡 1 个
    r = _add(conn, "交报告", "end", deadline=NOW + DAY)
    actions.do_snooze(conn, {"task_id": r["task_id"], "until": NOW + 7200})
    conn.close()

    body = client.get("/api/funnel").json()
    by_id = {l["id"]: l for l in body["layers"]}
    assert by_id["future_period"]["blocked_count"] == 1
    assert by_id["future_period"]["blocked_tasks"][0]["title"] == "明日原神"
    assert by_id["snooze"]["blocked_count"] == 1
    assert by_id["snooze"]["blocked_tasks"][0]["title"] == "交报告"


def test_funnel_does_not_push(client):
    # 接口只算不弹:不该写 push_log
    conn = db.connect()
    _add(conn, "今日原神", "end", deadline=NOW + int(0.5 * DAY), recurrence_interval=DAY)
    conn.close()
    client.get("/api/funnel")
    conn = db.connect()
    n, _ = db.push_stats(conn, db.list_active(conn)[0]["id"])
    conn.close()
    assert n == 0


def test_funnel_will_push_lists_survivors(client):
    conn = db.connect()
    _add(conn, "今日原神", "end", deadline=NOW + int(0.5 * DAY), recurrence_interval=DAY)
    conn.close()
    body = client.get("/api/funnel").json()
    assert any(t["title"] == "今日原神" for t in body["will_push"])
