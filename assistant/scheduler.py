"""调度:判断哪些提醒该弹了"""
from datetime import datetime

from .inbox import load_inbox
from .notifier import notify


def due(reminder):
    if reminder.get("status") != "pending":
        return False
    t = reminder.get("time", "").strip()
    if not t:  # 空时间 = 立即
        return True
    try:
        return datetime.now() >= datetime.strptime(t, "%Y-%m-%d %H:%M")
    except ValueError:
        return False


def tick():
    fired = False
    for r in load_inbox()["reminders"]:
        if due(r):
            notify(r)
            fired = True
    return fired
