"""任务查询:为主面板提供已加工的数据(倒计时、距上次天数、log 值、tag)。

属于 core 层:读 db + engine,不做 UI。
"""
from datetime import datetime

from . import db, engine


def _days_since(date_str):
    if not date_str:
        return None
    d = datetime.strptime(date_str.split()[0], "%Y-%m-%d").date()
    return (datetime.now().date() - d).days


def _remain(deadline):
    """返回 (剩余天, 剩余秒)。已过期返回负。"""
    if not deadline:
        return None, None
    try:
        dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except ValueError:
        dt = datetime.strptime(deadline.split()[0], "%Y-%m-%d")
    delta = dt - datetime.now()
    return delta.days, int(delta.total_seconds())


def _fmt_countdown(deadline):
    """人话倒计时:'已过期' / '今天 18:00' / '还剩 2 天'。"""
    days, secs = _remain(deadline)
    if secs is None:
        return ""
    if secs <= 0:
        return "已过期"
    if days >= 1:
        return f"还剩 {days} 天"
    h = secs // 3600
    if h >= 1:
        return f"还剩 {h} 小时"
    return f"还剩 {secs // 60} 分钟"


def _task_tags(conn, tid):
    return [r["name"] for r in conn.execute(
        "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id WHERE tt.task_id=?",
        (tid,)).fetchall()]


def all_tags(conn=None):
    close = conn is None
    conn = conn or db.connect()
    rows = [r["name"] for r in conn.execute("SELECT name FROM tags ORDER BY name").fetchall()]
    if close:
        conn.close()
    return rows


def dashboard_data(conn=None):
    """返回 {'starts': [...], 'ends': [...]},每项含显示所需字段。"""
    close = conn is None
    conn = conn or db.connect()
    ends_raw, starts_raw = engine.today_lists(conn)
    starts, ends = [], []
    for t in starts_raw:
        starts.append({**t,
                       "importance": t["importance"],
                       "days_since": _days_since(t["anchor"]),
                       "tags": _task_tags(conn, t["id"])})
    for t in ends_raw:
        ends.append({**t,
                     "importance": t["importance"],
                     "countdown": _fmt_countdown(t["deadline"]),
                     "tags": _task_tags(conn, t["id"])})
    if close:
        conn.close()
    return {"starts": starts, "ends": ends}


def task_detail(tid, conn=None):
    """单任务完整详情(含 schedule 字段 + tags + 当前 importance)。

    返回 None 表示任务不存在。importance 按 drive 现算,过期 end 给 OVERDUE 大数。
    """
    close = conn is None
    conn = conn or db.connect()
    row = conn.execute(
        "SELECT t.*, s.deadline, s.anchor, s.cycle_days FROM tasks t"
        " JOIN schedule s ON s.task_id=t.id WHERE t.id=?",
        (tid,)).fetchone()
    if row is None:
        if close:
            conn.close()
        return None
    t = dict(row)
    t["tags"] = _task_tags(conn, tid)
    if t["drive"] == "end":
        t["importance"] = engine.end_importance(t["deadline"])
        t["countdown"] = _fmt_countdown(t["deadline"])
    else:
        t["importance"] = engine.start_importance(t["anchor"], t["cycle_days"])
        t["days_since"] = _days_since(t["anchor"])
    if close:
        conn.close()
    return t


def task_pushes(tid, conn=None):
    """该任务的提醒记录(push_log 倒序:最新在前)。"""
    close = conn is None
    conn = conn or db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT pushed_at, stage, response FROM push_log"
        " WHERE task_id=? ORDER BY pushed_at DESC, id DESC",
        (tid,)).fetchall()]
    if close:
        conn.close()
    return rows

