"""重要性引擎:算 start(log)/end(-log)重要性,产出今日清单。

时间与周期内部一律 Unix 秒级整数(见 docs/schema.md),SQL 只取数。
START/DDL 都按秒算,精度统一;x<1 时 log 自然为负排最后,无需 -inf 特判。
"""
import math

from . import db
from .timeutil import SECONDS_PER_DAY, now_ts

OVERDUE = 1e9  # end 任务已过期时的固定大值,表示"已错过,最高优先"

# x 的下限保护:anchor 恰等于 now(x=0)时避免 log(0)=-inf。
# 取一个很小的正数,log 后是有限负数,仍排最后,且能正常 JSON 序列化。
_MIN_X = 1e-4


def start_importance(anchor, cycle_days, now=None):
    """log(距今秒数 / 周期秒数)。x<1 为负(还没到周期),x>=1 为正且缓慢上升。

    anchor / now 均为 Unix 秒级 int;now 缺省取当前。anchor 为 None 或周期非法返回 0。
    """
    now = now if now is not None else now_ts()
    if anchor is None or not cycle_days or cycle_days <= 0:
        return 0.0
    x = (now - int(anchor)) / (cycle_days * SECONDS_PER_DAY)
    if x <= 0:
        x = _MIN_X          # 刚建/刚做完:给一个有限负值,排最后但不崩 JSON
    return math.log(x)


def end_importance(deadline, now=None):
    """-log(剩余天数)。剩余<=0(已过期)返回 OVERDUE。

    deadline / now 均为 Unix 秒级 int;now 缺省取当前。deadline 为 None 返回 0。
    剩余换算成天数再取 log,保持数值范围与前端 OVERDUE/着色阈值兼容。
    """
    now = now if now is not None else now_ts()
    if deadline is None:
        return 0.0
    remain_days = (int(deadline) - now) / SECONDS_PER_DAY
    if remain_days <= 0:
        return OVERDUE
    return -math.log(remain_days)


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
