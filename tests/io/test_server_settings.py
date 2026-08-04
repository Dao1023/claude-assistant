"""测试:设置接口 GET/PUT /api/settings。用临时 DB + TestClient。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, settings
from assistant.io.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)
    db.init_db()
    yield TestClient(create_app())
    monkeypatch.setattr(settings, "_cache", None)


def test_get_returns_editable_and_readonly(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    keys = [i["key"] for i in body["editable"]]
    assert "crisis_importance" in keys and "poll_interval" in keys
    assert len(body["readonly"]) >= 3


def test_put_updates_value(client):
    r = client.put("/api/settings", json={"crisis_importance": 1.5})
    assert r.status_code == 200
    val = next(i for i in r.json()["editable"] if i["key"] == "crisis_importance")
    assert val["value"] == 1.5


def test_put_rejects_out_of_range(client):
    r = client.put("/api/settings", json={"escalate_nags": 999})
    assert r.status_code == 400


def test_put_rejects_unknown_key(client):
    r = client.put("/api/settings", json={"bogus": 1})
    assert r.status_code == 400


# ---------- SPA catch-all 不得吞掉 /api ----------

def test_get_settings_returns_json_not_html(client):
    # 接口必须返回 JSON;若被 SPA 回退成 index.html(text/html)则说明路由没生效
    r = client.get("/api/settings")
    assert r.headers["content-type"].startswith("application/json")


def test_unknown_api_returns_404_json_not_spa(client, tmp_path, monkeypatch):
    # 构造一个有 dist 的环境,验证未匹配的 /api/* 回 404 而非 index.html
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setattr("assistant.io.server.WEB_DIST", dist)
    c = TestClient(create_app())
    r = c.get("/api/no-such-endpoint")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
