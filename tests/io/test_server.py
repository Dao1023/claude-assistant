"""测试:HTTP 写接口(io/server.py),用 TestClient + 临时 DB。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db
from assistant.io.server import app

TODAY = datetime.now().date()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """每个测试独立临时 DB;路由内 db.connect() 动态读 config.DB_PATH。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return TestClient(app)


def _add(client, **kw):
    payload = {"title": "任务", "drive": "end", "deadline": str(TODAY) + " 23:59"}
    payload.update(kw)
    return client.post("/api/tasks", json=payload)


def test_add_task(client):
    r = _add(client, title="写周报", tags=["公司"])
    assert r.status_code == 201
    tid = r.json()["task_id"]
    assert client.get(f"/api/tasks/{tid}").json()["title"] == "写周报"


def test_add_end_recurrence_days(client):
    # end 传 recurrence_days,详情应能看到(秒->天数)
    r = _add(client, recurrence_days=7)
    tid = r.json()["task_id"]
    assert client.get(f"/api/tasks/{tid}").json()["recurrence_days"] == 7.0


def test_add_start_expected_days_not_auto_cyclic(client):
    # start 填 expected_days 不自动变周期(解耦)
    r = client.post("/api/tasks", json={
        "title": "论文", "drive": "start", "expected_days": 15})
    tid = r.json()["task_id"]
    d = client.get(f"/api/tasks/{tid}").json()
    assert d["expected_days"] == 15.0 and d["is_cyclic"] == 0


def test_add_invalid_drive_rejected(client):
    r = client.post("/api/tasks", json={"title": "x", "drive": "wrong"})
    assert r.status_code == 422            # Pydantic 校验失败


def test_update_task(client):
    tid = _add(client).json()["task_id"]
    r = client.put(f"/api/tasks/{tid}", json={"title": "改名了", "priority": 5})
    assert r.status_code == 200 and r.json()["updated"]
    d = client.get(f"/api/tasks/{tid}").json()
    assert d["title"] == "改名了" and d["priority"] == 5


def test_update_task_tags(client):
    # 编辑改 tag:去掉「学习」换「科研」,应生效(覆盖式)
    tid = _add(client, tags=["学习"]).json()["task_id"]
    assert client.get(f"/api/tasks/{tid}").json()["tags"] == ["学习"]
    r = client.put(f"/api/tasks/{tid}", json={"tags": ["科研"]})
    assert r.status_code == 200 and r.json()["updated"]
    assert client.get(f"/api/tasks/{tid}").json()["tags"] == ["科研"]


def test_update_task_clear_tags(client):
    # 传空数组 → 清空所有 tag
    tid = _add(client, tags=["学习", "科研"]).json()["task_id"]
    client.put(f"/api/tasks/{tid}", json={"tags": []})
    assert client.get(f"/api/tasks/{tid}").json()["tags"] == []


def test_update_task_without_tags_keeps_existing(client):
    # 不传 tags 字段 → 不动现有 tag(只改 title)
    tid = _add(client, tags=["学习"]).json()["task_id"]
    client.put(f"/api/tasks/{tid}", json={"title": "只改名"})
    assert client.get(f"/api/tasks/{tid}").json()["tags"] == ["学习"]


def test_done_cyclic_end_clones(client):
    # end 周期(recurrence_days=1)完成,克隆出下一个实例
    tid = _add(client, recurrence_days=1).json()["task_id"]
    r = client.post(f"/api/tasks/{tid}/done")
    assert r.json()["cyclic"] is True
    active = client.get("/api/tasks").json()["ends"]
    assert len(active) == 1 and active[0]["id"] != tid


def test_close_task(client):
    tid = _add(client).json()["task_id"]
    assert client.post(f"/api/tasks/{tid}/close").json()["closed"]
    assert db.get_task(db.connect(), tid)["status"] == "closed"


def test_snooze_logs_push(client):
    tid = _add(client).json()["task_id"]
    assert client.post(f"/api/tasks/{tid}/snooze").json()["snoozed"]
    pushes = client.get(f"/api/tasks/{tid}/pushes").json()["pushes"]
    assert len(pushes) == 1 and pushes[0]["response"] == "snoozed"


def test_snooze_with_until_and_unsnooze(client):
    tid = _add(client).json()["task_id"]
    # 推迟到指定时间
    r = client.post(f"/api/tasks/{tid}/snooze", json={"until": "2099-01-01 08:00"})
    assert r.json()["snoozed"]
    assert client.get(f"/api/tasks/{tid}").json()["snooze_until"] == "2099-01-01 08:00"
    # 取消推迟
    assert client.delete(f"/api/tasks/{tid}/snooze").json()["unsnoozed"]
    assert client.get(f"/api/tasks/{tid}").json()["snooze_until"] is None


def test_overdue_end_auto_closed_on_list(client):
    # deadline 已过 → GET /api/tasks 时自动 closed,不在 ends 列表
    r = _add(client, deadline="2020-01-01 00:00")
    tid = r.json()["task_id"]
    ends = client.get("/api/tasks").json()["ends"]
    assert all(t["id"] != tid for t in ends)
    assert db.get_task(db.connect(), tid)["status"] == "closed"


def test_write_on_missing_task_404(client):
    assert client.put("/api/tasks/不存在", json={"title": "x"}).status_code == 404
    assert client.post("/api/tasks/不存在/done").status_code == 404
    assert client.post("/api/tasks/不存在/close").status_code == 404
    assert client.post("/api/tasks/不存在/snooze").status_code == 404
