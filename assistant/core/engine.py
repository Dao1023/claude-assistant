"""重要性引擎:算 start(log)/end(-log)重要性,产出今日清单。

时间与周期内部一律 Unix 秒级整数(见 docs/schema.md),SQL 只取数。
start 用 anchor + expected_duration,end 用 deadline + recurrence_interval,字段级拆分。

过期 end 任务在进入引擎前已被 actions.close_overdue 关闭,故引擎不会收到过期任务,
也无需 OVERDUE 哨兵——「超时即关闭」在 actions 层处理,不属于重要性计算。
"""
import math

from . import db
from .timeutil import SECONDS_PER_DAY, now_ts

# x 的下限保护:anchor 恰等于 now(x=0)时避免 log(0)=-inf。
# 取一个很小的正数,log 后是有限负数,仍排最后,且能正常 JSON 序列化。
_MIN_X = 1e-4


def start_importance(anchor, expected_duration, now=None):
    """log(距今秒数 / 预期间隔秒数)。x<1 为负(还没到周期),x>=1 为正且缓慢上升。

    anchor / expected_duration / now 均为 Unix 秒级 int;now 缺省取当前。
    anchor 或 expected_duration 为空/非正返回 0(无法归一化,不参与排序)。
    """
    now = now if now is not None else now_ts()
    if anchor is None or not expected_duration or expected_duration <= 0:
        return 0.0
    x = (now - int(anchor)) / int(expected_duration)
    if x <= 0:
        x = _MIN_X          # 刚建/刚做完:给一个有限负值,排最后但不崩 JSON
    return math.log(x)


def end_importance(deadline, now=None):
    """-log(剩余天数)。剩余越少值越大。

    deadline / now 均为 Unix 秒级 int;now 缺省取当前。deadline 为 None 返回 0。
    剩余换算成天数再取 log,保持数值范围直观。过期任务已被 close_overdue 关闭,
    不会到这里;若剩余恰为 0(边界),返回 0。
    """
    now = now if now is not None else now_ts()
    if deadline is None:
        return 0.0
    remain_days = (int(deadline) - now) / SECONDS_PER_DAY
    if remain_days <= 0:
        return 0.0          # 边界:恰到期。正常情况过期任务已被关闭,不会进入引擎
    return -math.log(remain_days)


def today_lists(conn=None):
    """产出今日清单:end 按剩余时间升序,start 按重要性降序。

    调用方应先跑 actions.close_overdue,确保过期 end 任务已关闭、不在此列。
    """
    close_conn = conn is None
    conn = conn or db.connect()
    ends, starts = [], []
    for r in db.list_active(conn):
        item = {"id": r["id"], "title": r["title"], "drive": r["drive"],
                "deadline": r["deadline"], "anchor": r["anchor"],
                "expected_duration": r["expected_duration"],
                "recurrence_interval": r["recurrence_interval"],
                "priority": r["priority"]}
        if r["drive"] == "end":
            item["importance"] = end_importance(r["deadline"])
            ends.append(item)
        else:
            item["importance"] = start_importance(r["anchor"], r["expected_duration"])
            starts.append(item)
    ends.sort(key=lambda x: (x["deadline"] is None, x["deadline"]))
    starts.sort(key=lambda x: x["importance"], reverse=True)
    if close_conn:
        conn.close()
    return ends, starts
