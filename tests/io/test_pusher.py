"""测试:推送生命周期(io/pusher)的集成行为:end 优先、限量、过滤生效。用临时 DB。

纯过滤/定档逻辑(冷却、未来周期、推迟、档位)已抽到 core/funnel,
其单元测试见 tests/core/test_funnel.py;本文件只测 tick_push 的端到端挑选行为。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import actions, db, settings
from assistant.io import pusher

DAY = 86400
NOW = int(time.time())


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)   # 隔离设置缓存,指向测试库
    db.init_db()
    c = db.connect()
    # 关掉免打扰:夜间窗口置空 + 清临时 DND,让推送行为不依赖跑测试的钟点。
    # DND 本身的判断由 tests/core/test_funnel.py 专门覆盖。
    db.set_setting(c, "dnd_night_end", 0)
    db.set_setting(c, "dnd_until", "")
    yield c
    c.close()
    monkeypatch.setattr(settings, "_cache", None)


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
