"""测试:推送生命周期(io/pusher)的按需冷却与一次一个。用临时 DB。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import actions, db
from assistant.io import pusher

DAY = 86400
NOW = int(time.time())


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


# ---------- 冷却 ∝ 任务间隔 ----------

def _task(drive, **kw):
    return {"id": "x", "title": "t", "drive": drive, "snooze_until": None, **kw}


def test_cooldown_scales_with_interval():
    # end 周期 1 天 → 冷却 6h。5h 前推过 → 仍冷却;7h 前 → 不冷却
    t = _task("end", recurrence_interval=DAY)
    assert pusher._cooling_down(t, NOW - 5 * 3600, now=NOW) is True
    assert pusher._cooling_down(t, NOW - 7 * 3600, now=NOW) is False


def test_cooldown_uses_expected_duration_for_start():
    # start 预期 15 天 → 冷却 3.75 天。1 天前推过 → 冷却;4 天前 → 不冷却
    t = _task("start", expected_duration=15 * DAY)
    assert pusher._cooling_down(t, NOW - DAY, now=NOW) is True
    assert pusher._cooling_down(t, NOW - 4 * DAY, now=NOW) is False


def test_cooldown_fallback_when_no_interval():
    # 无间隔字段 → 兜底间隔 1h,冷却 = 1h×1/4 = 15 分钟
    t = _task("end", recurrence_interval=None)
    assert pusher._cooling_down(t, NOW - 600, now=NOW) is True    # 10 分钟前,仍冷却
    assert pusher._cooling_down(t, NOW - 1800, now=NOW) is False  # 30 分钟前,不冷却


def test_no_cooldown_when_never_pushed():
    t = _task("end", recurrence_interval=DAY)
    assert pusher._cooling_down(t, None, now=NOW) is False


# ---------- snooze_until 优先 ----------

def test_snooze_until_in_future_cools():
    t = _task("end", recurrence_interval=DAY, snooze_until=NOW + 3600)
    # 即使从没推过,推迟未到点也冷却
    assert pusher._cooling_down(t, None, now=NOW) is True


def test_snooze_until_expired_resumes():
    t = _task("end", recurrence_interval=DAY, snooze_until=NOW - 3600)
    assert pusher._cooling_down(t, None, now=NOW) is False


# ---------- 一次一个,end 优先 ----------

def test_tick_push_picks_end_over_start(conn, monkeypatch):
    # 一个 start + 一个 end,都没推过 → 应选 end
    actions.do_add(conn, {"title": "论文", "drive": "start", "expected_duration": 15 * DAY})
    actions.do_add(conn, {"title": "交报告", "drive": "end", "deadline": NOW + DAY})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 1 and shown == ["交报告"]


def test_tick_push_only_one_per_tick(conn, monkeypatch):
    # 两个 end 都该催 → 一次只弹一个
    actions.do_add(conn, {"title": "任务A", "drive": "end", "deadline": NOW + DAY})
    actions.do_add(conn, {"title": "任务B", "drive": "end", "deadline": NOW + 2 * DAY})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 1 and len(shown) == 1


def test_tick_push_falls_back_to_start(conn, monkeypatch):
    # 没有可推的 end(已冷却)→ 推 start
    actions.do_add(conn, {"title": "论文", "drive": "start", "expected_duration": 15 * DAY})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 1 and shown == ["论文"]


def test_tick_push_skips_snoozed(conn, monkeypatch):
    # 唯一任务被推迟到未来 → 不弹
    r = actions.do_add(conn, {"title": "交报告", "drive": "end", "deadline": NOW + DAY})
    actions.do_snooze(conn, {"task_id": r["task_id"], "until": NOW + 7200})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 0 and shown == []


# ---------- 周期 end:不提前催下一天(通知层过滤) ----------

def test_future_period_helper():
    # 明天的每日(剩余 1.5 周期)→ 是未来周期,该过滤;今天的每日(剩余 0.5 周期)→ 不过滤
    future = _task("end", deadline=NOW + int(1.5 * DAY), recurrence_interval=DAY)
    current = _task("end", deadline=NOW + int(0.5 * DAY), recurrence_interval=DAY)
    oneoff = _task("end", deadline=NOW + 30 * DAY, recurrence_interval=None)
    assert pusher._is_future_period(future, now=NOW) is True
    assert pusher._is_future_period(current, now=NOW) is False
    assert pusher._is_future_period(oneoff, now=NOW) is False   # 一次性 end 不过滤


def test_tick_push_skips_tomorrows_daily(conn, monkeypatch):
    # 只有「明天的每日」(剩余 > 1 周期)→ 不该弹
    actions.do_add(conn, {"title": "明日原神", "drive": "end",
                          "deadline": NOW + int(1.5 * DAY), "recurrence_interval": DAY})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 0 and shown == []


def test_tick_push_picks_todays_daily(conn, monkeypatch):
    # 「今天的每日」(剩余 < 1 周期)→ 该弹
    actions.do_add(conn, {"title": "今日原神", "drive": "end",
                          "deadline": NOW + int(0.5 * DAY), "recurrence_interval": DAY})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 1 and shown == ["今日原神"]


def test_tick_push_future_daily_falls_back_to_start(conn, monkeypatch):
    # 明天的每日被过滤后,还有 start → 退而推 start
    actions.do_add(conn, {"title": "明日原神", "drive": "end",
                          "deadline": NOW + int(1.5 * DAY), "recurrence_interval": DAY})
    actions.do_add(conn, {"title": "论文", "drive": "start", "expected_duration": 15 * DAY})
    shown = []
    monkeypatch.setattr(pusher, "show_task_card", lambda task, stage, *a: shown.append(task["title"]))
    n = pusher.tick_push()
    assert n == 1 and shown == ["论文"]


# ---------- 克隆清 snooze_until ----------

def test_clone_clears_snooze(conn):
    r = actions.do_add(conn, {"title": "原神每日", "drive": "end",
                               "deadline": NOW + 3600, "recurrence_interval": DAY})
    actions.do_snooze(conn, {"task_id": r["task_id"], "until": NOW + 7200})
    actions.do_done(conn, {"task_id": r["task_id"]})
    new = db.list_active(conn, "end")[0]
    assert new["snooze_until"] is None
