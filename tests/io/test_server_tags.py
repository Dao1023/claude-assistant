"""测试:标签层级 HTTP 端点(io/server.py),TestClient + 临时 DB。"""
import sys
from datetime import datetime
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
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return TestClient(app)


def _add(client, **kw):
    payload = {"title": "任务", "drive": "end", "deadline": str(TODAY) + " 23:59"}
    payload.update(kw)
    return client.post("/api/tasks", json=payload)


# ---------- GET /api/tasks 的 tags 字段 ----------

def test_dashboard_tags_flat_with_parent(client):
    _add(client, tags=["科研"])
    r = client.post("/api/tags", json={"name": "工作"})
    wid = r.json()["id"]
    kid = next(t["id"] for t in _all(client) if t["name"] == "科研")
    client.put(f"/api/tags/{kid}", json={"parent_id": wid})
    tags = client.get("/api/tasks").json()["tags"]
    by_name = {t["name"]: t["parent"] for t in tags}
    assert by_name == {"工作": None, "科研": "工作"}


def _all(client):
    out = []

    def walk(nodes):
        for n in nodes:
            out.append(n)
            walk(n["children"])

    walk(client.get("/api/tags").json()["tree"])
    return out


# ---------- POST /api/tags ----------

def test_tag_add_ok(client):
    r = client.post("/api/tags", json={"name": "工作"})
    assert r.status_code == 201
    assert r.json()["id"] >= 1
    assert client.post("/api/tags", json={"name": "工作"}).status_code == 400  # 重名


def test_tag_add_blank_400(client):
    assert client.post("/api/tags", json={"name": " "}).status_code == 400


def test_tag_add_missing_parent_404(client):
    assert client.post("/api/tags", json={"name": "x", "parent_id": 999}).status_code == 404


# ---------- PUT /api/tags/{id} ----------

def test_tag_rename_and_move(client):
    wid = client.post("/api/tags", json={"name": "工作"}).json()["id"]
    kid = client.post("/api/tags", json={"name": "科研", "parent_id": wid}).json()["id"]
    assert client.put(f"/api/tags/{kid}", json={"name": "公司"}).json()["updated"]
    # parent 不传 = 不动;传 null = 回根级
    assert client.put(f"/api/tags/{kid}", json={}).json()["updated"]
    node = next(n for n in _all(client) if n["name"] == "公司")
    assert node["parent_id"] == wid
    assert client.put(f"/api/tags/{kid}", json={"parent_id": None}).json()["updated"]
    node = next(n for n in _all(client) if n["name"] == "公司")
    assert node["parent_id"] is None


def test_tag_move_cycle_400(client):
    wid = client.post("/api/tags", json={"name": "工作"}).json()["id"]
    kid = client.post("/api/tags", json={"name": "科研", "parent_id": wid}).json()["id"]
    assert client.put(f"/api/tags/{wid}", json={"parent_id": kid}).status_code == 400


def test_tag_update_missing_404(client):
    assert client.put("/api/tags/999", json={"name": "x"}).status_code == 404


# ---------- DELETE /api/tags/{id} ----------

def test_tag_delete_promotes_children(client):
    wid = client.post("/api/tags", json={"name": "工作"}).json()["id"]
    kid = client.post("/api/tags", json={"name": "科研", "parent_id": wid}).json()["id"]
    assert client.delete(f"/api/tags/{wid}").json()["deleted"]
    roots = client.get("/api/tags").json()["tree"]
    assert [r["id"] for r in roots] == [kid]


def test_tag_delete_unlinks_tasks(client):
    _add(client, tags=["科研"])
    kid = _all(client)[0]["id"]
    client.delete(f"/api/tags/{kid}")
    tid = client.get("/api/tasks").json()["ends"][0]["id"]
    c = db.connect().execute("SELECT COUNT(*) c FROM task_tags WHERE task_id=?", (tid,))
    assert c.fetchone()["c"] == 0


def test_tag_delete_missing_404(client):
    assert client.delete("/api/tags/999").status_code == 404
