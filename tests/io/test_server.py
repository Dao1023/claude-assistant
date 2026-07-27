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
    payload = {"title": "任务", "drive": "end", "deadline": str(TODAY) + " 18:00"}
    payload.update(kw)
    return client.post("/api/tasks", json=payload)


def test_add_task(client):
    r = _add(client, title="写周报", tags=["公司"])
    assert r.status_code == 201
    tid = r.json()["task_id"]
    assert client.get(f"/api/tasks/{tid}").json()["title"] == "写周报"


def test_add_cyclic_by_cycle_days(client):
    # 只传 cycle_days,应自动视为周期任务
    r = _add(client, cycle_days=7)
    tid = r.json()["task_id"]
    assert db.get_task(db.connect(), tid)["is_cyclic"] == 1


def test_add_invalid_drive_rejected(client):
    r = client.post("/api/tasks", json={"title": "x", "drive": "wrong"})
    assert r.status_code == 422            # Pydantic 校验失败


def test_update_task(client):
    tid = _add(client).json()["task_id"]
    r = client.put(f"/api/tasks/{tid}", json={"title": "改名了", "priority": 5})
    assert r.status_code == 200 and r.json()["updated"]
    d = client.get(f"/api/tasks/{tid}").json()
    assert d["title"] == "改名了" and d["priority"] == 5


def test_done_cyclic_clones(client):
    tid = _add(client, cycle_days=1, is_cyclic=1).json()["task_id"]
    r = client.post(f"/api/tasks/{tid}/done")
    assert r.json()["cyclic"] is True
    # 原任务 done,克隆出一个新 active end 任务
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


def test_write_on_missing_task_404(client):
    assert client.put("/api/tasks/不存在", json={"title": "x"}).status_code == 404
    assert client.post("/api/tasks/不存在/done").status_code == 404
    assert client.post("/api/tasks/不存在/close").status_code == 404
    assert client.post("/api/tasks/不存在/snooze").status_code == 404
