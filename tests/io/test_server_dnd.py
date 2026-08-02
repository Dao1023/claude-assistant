"""测试:临时免打扰接口 PUT/DELETE /api/dnd。用临时 DB + TestClient。"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, settings
from assistant.io.server import create_app

NOW = int(time.time())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)
    db.init_db()
    yield TestClient(create_app())
    monkeypatch.setattr(settings, "_cache", None)


def test_put_dnd_sets_until(client):
    r = client.put("/api/dnd", json={"until": "2099-01-01 08:00"})
    assert r.status_code == 200
    assert r.json()["until"] is not None          # 已设到期时刻


def test_delete_dnd_clears(client):
    client.put("/api/dnd", json={"until": "2099-01-01 08:00"})
    r = client.delete("/api/dnd")
    assert r.status_code == 200
    assert r.json()["until"] is None               # 已立即恢复
