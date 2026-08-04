"""测试:通知过滤漏斗(core/funnel)纯函数。用临时 DB(settings 读阈值)。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, funnel, settings

DAY = 86400
NOW = int(time.time())


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """settings 阈值读库;换到临时库并重置缓存,隔离真实数据。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)
    db.init_db()
    yield
    monkeypatch.setattr(settings, "_cache", None)


def _task(drive, **kw):
    return {"id": "x", "title": "t", "drive": drive, "snooze_until": None, **kw}


def _ctx(now=NOW, last_at=None):
    return {"now": now, "last_at": last_at}


# ---------- 未来周期 ----------

def test_future_period_blocks_tomorrows_daily():
    future = _task("end", deadline=NOW + int(1.5 * DAY), recurrence_interval=DAY)
    current = _task("end", deadline=NOW + int(0.5 * DAY), recurrence_interval=DAY)
    oneoff = _task("end", deadline=NOW + 30 * DAY, recurrence_interval=None)
    assert funnel.check_future_period(future, _ctx()) is not None
    assert funnel.check_future_period(current, _ctx()) is None
    assert funnel.check_future_period(oneoff, _ctx()) is None   # 一次性 end 不过滤


# ---------- 推迟 ----------

def test_snooze_blocks_until_reached():
    t = _task("end", recurrence_interval=DAY, snooze_until=NOW + 3600)
    assert funnel.check_snooze(t, _ctx()) is not None
    t2 = _task("end", recurrence_interval=DAY, snooze_until=NOW - 3600)
    assert funnel.check_snooze(t2, _ctx()) is None


# ---------- run_pipe:只算第一层 ----------

def test_run_pipe_reports_first_block_only():
    # 既是未来周期又推迟 → 算在 future_period(第一层),不再算 snooze
    t = _task("end", deadline=NOW + int(1.5 * DAY), recurrence_interval=DAY,
              snooze_until=NOW + 7200)
    layer, reason = funnel.run_pipe(t, _ctx())
    assert layer == "future_period"


def test_run_pipe_passes_clear_task():
    t = _task("end", deadline=NOW + int(0.5 * DAY), recurrence_interval=DAY)
    layer, reason = funnel.run_pipe(t, _ctx())
    assert layer is None and reason is None


# ---------- 定档位 ----------

def test_stage_gentle_by_default():
    t = _task("start", expected_duration=15 * DAY)
    assert funnel.stage(t, 0) == "gentle"


def test_stage_escalates_after_enough_nags():
    t = _task("end", deadline=NOW + 30 * DAY)
    assert funnel.stage(t, settings.get("escalate_nags")) == "escalating"


def test_stage_crisis_when_close():
    t = _task("end", deadline=NOW + 3600)        # 1 小时后截止,重要性 >= 危机阈值
    assert funnel.stage(t, 0) == "crisis"


# ---------- 免打扰总闸(dnd_active)----------

def _at(hour, minute=0):
    """今天指定时刻的 Unix 秒。"""
    from datetime import datetime
    d = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return int(d.timestamp())


def test_dnd_manual_until_blocks_then_clear_restores():
    settings.set("dnd_night_end", 0)               # 关掉夜间窗口,隔离出手动 DND 的效果
    settings.set_dnd_until(NOW + 3600)             # 手动免打扰 1 小时
    assert funnel.dnd_active(NOW) is not None      # 命中
    assert funnel.dnd_active(NOW + 7200) is None   # 过期自动恢复
    settings.set_dnd_until(NOW + 3600)
    settings.set_dnd_until(None)                   # 立即恢复
    assert funnel.dnd_active(NOW) is None


def test_dnd_night_window():
    settings.set("dnd_night_end", 8)
    assert funnel.dnd_active(_at(3)) is not None   # 凌晨 3 点:冻结
    assert funnel.dnd_active(_at(12)) is None      # 中午:畅通
    assert funnel.dnd_active(_at(23)) is None      # 23 点:不跨天,夜间仅 0~8 点


def test_dnd_night_end_zero_disables_night():
    settings.set("dnd_night_end", 0)               # 0 点恢复 = 夜间窗口为空
    assert funnel.dnd_active(_at(3)) is None
