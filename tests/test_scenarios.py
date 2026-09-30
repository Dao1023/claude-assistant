"""提醒场景 × 计时器引擎拟合测试。

职责纪律(V4.1,主人 2026-10 定音):
    计时器是女仆给自己的闹钟。闹钟就是闹钟——只管到点响。
    看时间、看主人、看环境、决定说不说、决定下一个闹钟设几点,
    全部是女仆(大脑)醒来之后的事。闹钟不做任何判断。

因此场景映射只有三种动作:
    add    女仆上闹钟(每天英语/每周学习/客户截止/档案扫描心跳)
    reset  女仆改闹钟(跳跃提醒:下次隔多久她醒来自己定)
    remove 女仆撤闹钟(事情办完/不再需要)
条件触发/勿扰/摸鱼判断 = 女仆醒来看了再定,不是闹钟的功能。

时间线:假时间戳,T0 = 某周一 07:00。
"""
import pytest

from assistant.timers import TimerEngine

DAY = 86400
T0 = 1_000_000  # 周一 07:00


@pytest.fixture()
def eng(tmp_path):
    # review_every 设成天文数字:场景测试只关心女仆的闹钟,
    # 本体回顾节拍在 test_timers.py 单独覆盖
    e = TimerEngine(path=tmp_path / "timers.json", review_every=10 ** 9)
    e._state["meta"]["last_review"] = T0
    return e


# ---------- 早晨例行:闹钟到点,合并成一次响 ----------

def test_morning_routine_merged_single_wake(eng):
    """英语(08:00) + 日程分享(08:30)两个闹钟 → 一次唤醒合并说完。
    (要不要拆开说、什么语气说,女仆醒来自己定——引擎只保证不多响。)"""
    eng.add("interval", at=T0 + 3600, every=DAY, label="英语每日",
            payload="该学英语了", now=T0)
    eng.add("interval", at=T0 + 5400, every=DAY, label="日程分享",
            payload="给主人分享今天的日程建议", now=T0)
    b = eng.due_batch(now=T0 + 3600, awake=True)
    assert b["reason"] == "timers" and b["count"] == 1 and "英语" in b["message"]
    b = eng.due_batch(now=T0 + 5400, awake=True)
    assert b["count"] == 1 and "日程" in b["message"]
    # 次日 08:30 一次唤醒 = 两件合并
    b = eng.due_batch(now=T0 + DAY + 5400, awake=True)
    assert b["count"] == 2
    assert "英语" in b["message"] and "日程" in b["message"]


# ---------- 每周学习 ----------

def test_weekly_study_block(eng):
    eng.add("interval", at=T0 + 3 * DAY, every=7 * DAY, label="周学习",
            payload="本周学习块到了", now=T0)
    assert eng.due_batch(now=T0 + 3 * DAY - 1, awake=True) is None
    b = eng.due_batch(now=T0 + 3 * DAY, awake=True)
    assert b["count"] == 1 and "周学习" in b["message"]
    t = eng.list()[0]
    assert t["fire_at"] == T0 + 10 * DAY            # 恰好下周同一时刻


# ---------- 客户催办:截止到点,之后的升级是女仆重上闹钟 ----------

def test_client_deadline_escalation_is_maid_rearming(eng):
    """周五 17:00 闹钟响;女仆醒来发现没办完,自己决定 2 小时后再上闹钟;
    再醒再判断。引擎不提供「升级」功能——那是女仆的行为模式。"""
    eng.add("once", at=T0 + 4 * DAY + 10 * 3600, label="客户催办",
            payload="客户要的方案 17:00 截止", now=T0)
    b = eng.due_batch(now=T0 + 4 * DAY + 10 * 3600, awake=True)
    assert b["count"] == 1 and "客户" in b["message"]
    # 女仆的决策(在她脑子里):没办完 → 温和升级,+2h 再上闹钟
    eng.add("once", in_sec=2 * 3600, label="客户催办·二催",
            payload="主人,客户方案还没发哦,再检查一下?",
            now=T0 + 4 * DAY + 10 * 3600)
    b = eng.due_batch(now=T0 + 4 * DAY + 12 * 3600, awake=True)
    assert "二催" in b["message"]
    assert eng.list() == []                          # once 用完即清


# ---------- 女仆的核心循环:醒来 → 看情况 → 重排自己的闹钟 ----------

def test_maid_reschedules_her_own_alarms(eng):
    """跳跃提醒的完整模式:早上唤醒后,女仆看了主人的状态,
    决定中午再看一次;中午看完,决定傍晚再确认。
    引擎侧全程只做一件事:按 reset 给的时间响。"""
    tid = eng.add("interval", at=T0 + 3600, every=DAY, label="看主人",
                  payload="醒了,看看主人现在什么状态", now=T0)
    # 08:00 醒,看完决定:中午 12:00 再看(改闹钟,不给固定周期)
    eng.due_batch(now=T0 + 3600, awake=True)
    assert eng.reset(tid, at=T0 + 5 * 3600, now=T0 + 3600) is True
    assert eng.due_batch(now=T0 + 5 * 3600 - 1, awake=True) is None
    b = eng.due_batch(now=T0 + 5 * 3600, awake=True)
    assert b["count"] == 1
    # 中午看完决定:18:00 再确认;期间多次推进都不响
    eng.reset(tid, at=T0 + 11 * 3600, now=T0 + 5 * 3600)
    for probe in (6, 8, 10):
        assert eng.due_batch(now=T0 + probe * 3600, awake=True) is None
    assert eng.due_batch(now=T0 + 11 * 3600, awake=True)["count"] == 1


# ---------- 档案扫描心跳 + someday 浮现 ----------

def test_archive_scan_heartbeat_and_someday(eng):
    """扫描心跳每小时一响(重要性排序是大脑+事件层的事);
    someday 三天浮现一次。两个闹钟各自按点响,互不干扰。"""
    eng.add("interval", every=3600, label="档案扫描",
            payload="扫一遍档案:太久没办的事有没有该浮上来的", now=T0)
    eng.add("interval", every=3 * DAY, label="someday",
            payload="主人一直想学的'编曲',要不要这周排一点时间?", now=T0)
    fires = 0
    for h in range(1, 6):
        b = eng.due_batch(now=T0 + h * 3600, awake=True)
        if b and b["reason"] == "timers":
            fires += 1
    assert fires == 5                                 # 心跳稳定 1/h
    b = eng.due_batch(now=T0 + 3 * DAY, awake=True)
    assert "编曲" in b["message"]                     # 三天后浮现


# ---------- 周末睡懒觉:睡眠语义(引擎唯一保留的「判断」,daemon 级) ----------

def test_weekend_sleep_in(eng):
    """周六早八主人睡到中午:闹钟照点走但大脑不在 → daemon 记账不唤醒;
    醒来补一次,明天照常。这是 daemon 的睡眠/唤醒机制,不是闹钟的智能。"""
    sat_morning = T0 + 5 * DAY + 3600                 # 周六 08:00
    eng.add("interval", at=sat_morning, every=DAY, label="英语每日",
            payload="该学英语了", now=T0)
    assert eng.due_batch(now=sat_morning + 3600, awake=False) is None  # 睡眠
    assert len(eng.missed) == 1
    b = eng.due_batch(now=sat_morning + 4 * 3600, awake=True)
    assert b["reason"] == "missed" and "英语" in b["message"]
    assert eng.due_batch(now=sat_morning + 5 * 3600, awake=True) is None
    b = eng.due_batch(now=sat_morning + DAY, awake=True)
    assert b["reason"] == "timers" and b["count"] == 1
