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
    assert "cooldown_ratio" in keys and "poll_interval" in keys
    assert len(body["readonly"]) >= 3


def test_put_updates_value(client):
    r = client.put("/api/settings", json={"cooldown_ratio": 0.5})
    assert r.status_code == 200
    val = next(i for i in r.json()["editable"] if i["key"] == "cooldown_ratio")
    assert val["value"] == 0.5


def test_put_rejects_out_of_range(client):
    r = client.put("/api/settings", json={"escalate_nags": 999})
    assert r.status_code == 400


def test_put_rejects_unknown_key(client):
    r = client.put("/api/settings", json={"bogus": 1})
    assert r.status_code == 400
