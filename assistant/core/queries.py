"""任务查询:为主面板提供已加工的数据(倒计时、距上次天数、log 值、tag)。

属于 core 层:读 db + engine,不做 UI。
时间内部是 Unix 秒级 int;出口(deadline/anchor/created)转成字符串喂前端,
保持前端契约不变(见 core/timeutil.py)。
"""
from . import db, engine
from .timeutil import SECONDS_PER_DAY, now_ts, to_date_str, to_str


def _days_since(anchor_ts):
    """距今多少天(浮点,按秒差算)。None → None。"""
    if anchor_ts is None:
        return None
    return (now_ts() - int(anchor_ts)) / SECONDS_PER_DAY


def _remain(deadline_ts):
    """返回 (剩余天, 剩余秒)。已过期返回负。None → (None, None)。"""
    if deadline_ts is None:
        return None, None
    delta_sec = int(deadline_ts) - now_ts()
    return delta_sec // SECONDS_PER_DAY, delta_sec


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
    """返回 {'starts': [...], 'ends': [...]},每项含显示所需字段。

    出口把 deadline/anchor 转成字符串(start→'YYYY-MM-DD',end→'YYYY-MM-DD HH:MM'),
    前端契约不变。
    """
    close = conn is None
    conn = conn or db.connect()
    ends_raw, starts_raw = engine.today_lists(conn)
    starts, ends = [], []
    for t in starts_raw:
        starts.append({**t,
                       "importance": t["importance"],
                       "anchor": to_date_str(t["anchor"]),
                       "days_since": _days_since(t["anchor"]),
                       "tags": _task_tags(conn, t["id"])})
    for t in ends_raw:
        ends.append({**t,
                     "importance": t["importance"],
                     "deadline": to_str(t["deadline"]),
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
    created_str = to_str(t["created"])
    if t["drive"] == "end":
        t["importance"] = engine.end_importance(t["deadline"])
        t["countdown"] = _fmt_countdown(t["deadline"])
        t["deadline"] = to_str(t["deadline"])
    else:
        t["importance"] = engine.start_importance(t["anchor"], t["cycle_days"])
        t["days_since"] = _days_since(t["anchor"])
        t["anchor"] = to_date_str(t["anchor"])
    t["created"] = created_str
    if close:
        conn.close()
    return t


def task_pushes(tid, conn=None):
    """该任务的提醒记录(push_log 倒序:最新在前)。pushed_at 出口转字符串。"""
    close = conn is None
    conn = conn or db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT pushed_at, stage, response FROM push_log"
        " WHERE task_id=? ORDER BY pushed_at DESC, id DESC",
        (tid,)).fetchall()]
    for r in rows:
        r["pushed_at"] = to_str(r["pushed_at"])
    if close:
        conn.close()
    return rows

