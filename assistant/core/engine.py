"""重要性引擎:算 start(log)/end(-log)重要性,产出今日清单。

公式在 Python 算(见 docs/schema.md),SQL 只取数。
"""
import math
from datetime import datetime

from . import db

OVERDUE = 1e9  # end 任务已过期时的固定大值,表示"已错过,最高优先"


def _parse_date(s):
    """解析 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM' 为 date。"""
    if not s:
        return None
    return datetime.strptime(s.split()[0], "%Y-%m-%d").date()


def start_importance(anchor, cycle_days, today=None):
    """log(距今天数 / 正常周期)。x<=0 返回 -inf(还没到周期)。"""
    today = today or datetime.now().date()
    a = _parse_date(anchor)
    if a is None or not cycle_days or cycle_days <= 0:
        return 0.0
    x = (today - a).days / cycle_days
    if x <= 0:
        return float("-inf")
    return math.log(x)


def end_importance(deadline, today=None):
    """-log(剩余天数)。剩余<=0(已过期)返回 OVERDUE。"""
    today = today or datetime.now().date()
    d = _parse_date(deadline)
    if d is None:
        return 0.0
    remain = (d - today).days
    if remain <= 0:
        return OVERDUE
    return -math.log(remain)


def today_lists(conn=None):
    """产出今日清单:end 按剩余时间升序,start 按重要性降序。"""
    close_conn = conn is None
    conn = conn or db.connect()
    ends, starts = [], []
    for r in db.list_active(conn):
        item = {"id": r["id"], "title": r["title"], "drive": r["drive"],
                "deadline": r["deadline"], "anchor": r["anchor"],
                "cycle_days": r["cycle_days"], "priority": r["priority"]}
        if r["drive"] == "end":
            item["importance"] = end_importance(r["deadline"])
            ends.append(item)
        else:
            item["importance"] = start_importance(r["anchor"], r["cycle_days"])
            starts.append(item)
    ends.sort(key=lambda x: (x["deadline"] is None, x["deadline"]))
    starts.sort(key=lambda x: x["importance"], reverse=True)
    if close_conn:
        conn.close()
    return ends, starts
