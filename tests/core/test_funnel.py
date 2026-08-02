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


# ---------- 冷却 ∝ 任务间隔 ----------

def test_cooldown_scales_with_interval():
    # end 周期 1 天 → 冷却 6h。5h 前推过 → 仍冷却;7h 前 → 不冷却
    t = _task("end", recurrence_interval=DAY)
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - 5 * 3600)) is not None
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - 7 * 3600)) is None


def test_cooldown_uses_expected_duration_for_start():
    # start 预期 15 天 → 冷却 3.75 天。1 天前 → 冷却;4 天前 → 不冷却
    t = _task("start", expected_duration=15 * DAY)
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - DAY)) is not None
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - 4 * DAY)) is None


def test_cooldown_fallback_when_no_interval():
    # 无间隔字段 → 兜底 1h,冷却 = 1h×1/4 = 15 分钟
    t = _task("end", recurrence_interval=None)
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - 600)) is not None
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - 1800)) is None


def test_no_cooldown_when_never_pushed():
    t = _task("end", recurrence_interval=DAY)
    assert funnel.check_cooldown(t, _ctx(last_at=None)) is None


def test_cooldown_fallback_reads_settings():
    # 把兜底冷却改小到 300s,则 10 分钟前的推送不再冷却
    settings.set("cooldown_fallback", 300)
    t = _task("end", recurrence_interval=None)
    assert funnel.check_cooldown(t, _ctx(last_at=NOW - 600)) is None


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
