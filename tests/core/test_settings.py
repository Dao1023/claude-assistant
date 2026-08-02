"""测试:通知规则设置(core/settings)。用临时 DB。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)   # 隔离缓存
    db.init_db()
    c = db.connect()
    yield c
    c.close()
    monkeypatch.setattr(settings, "_cache", None)


def test_defaults_when_table_empty(conn):
    # 表里没存过 → 返回默认值
    assert settings.get("cooldown_ratio") == 0.25
    assert settings.get("escalate_nags") == 3
    assert settings.get("poll_interval") == 30


def test_set_then_get(conn):
    settings.set("cooldown_ratio", 0.5)
    assert settings.get("cooldown_ratio") == 0.5


def test_type_coercion(conn):
    settings.set("escalate_nags", "7")
    assert settings.get("escalate_nags") == 7          # int
    assert isinstance(settings.get("escalate_nags"), int)
    settings.set("cooldown_ratio", "0.4")
    assert isinstance(settings.get("cooldown_ratio"), float)


def test_validate_rejects_out_of_range(conn):
    with pytest.raises(ValueError):
        settings.set("cooldown_ratio", 9.9)            # 超 max
    with pytest.raises(ValueError):
        settings.set("escalate_nags", 0)               # 低于 min


def test_validate_rejects_unknown_key(conn):
    with pytest.raises(KeyError):
        settings.set("nope", 1)


def test_all_returns_editable_with_meta(conn):
    items = settings.all()
    keys = [i["key"] for i in items]
    assert "cooldown_ratio" in keys and "max_concurrent" in keys
    one = next(i for i in items if i["key"] == "cooldown_ratio")
    assert one["value"] == 0.25 and one["label"] and one["desc"]
    assert one["min"] == 0.05 and one["max"] == 1.0
