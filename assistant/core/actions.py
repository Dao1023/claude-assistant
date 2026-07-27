"""任务动作:任务的增/完成/改/关/稍后/查,操作 SQLite。

属于 core 层:纯任务逻辑,不碰弹窗/唤起/HTTP。
调用方:HTTP 接口(io/server.py)、催办小卡(io/pusher.py)。
时间字段内部一律 Unix 秒级 int(见 core/timeutil.py)。
"""
from . import db
from .timeutil import now_ts


def now():
    """当前 Unix 秒级时间戳(写 created / pushed_at 用)。"""
    return now_ts()


# ---------- 各动作 ----------

def do_add(conn, p):
    """新增任务。start 用 anchor + expected_duration;end 用 deadline + recurrence_interval。"""
    drive = p["drive"]
    anchor = p.get("anchor") or (now() if drive == "start" else None)
    tid = db.add_task(
        conn,
        title=p["title"],
        drive=drive,
        is_cyclic=p.get("is_cyclic", 0) if drive == "start" else 0,
        priority=p.get("priority", 3),
        note=p.get("note"),
        created=now(),
        deadline=p.get("deadline") if drive == "end" else None,
        anchor=anchor,
        expected_duration=p.get("expected_duration") if drive == "start" else None,
        recurrence_interval=p.get("recurrence_interval") if drive == "end" else None,
        tags=p.get("tags", []),
    )
    return {"task_id": tid, "title": p["title"]}


def _clone_next(conn, task, *, anchor=None, deadline=None):
    """克隆一个周期的下一个实例(继承 title/drive/priority/note/tags)。"""
    sched = conn.execute("SELECT * FROM schedule WHERE task_id=?", (task["id"],)).fetchone()
    db.add_task(
        conn, task["title"], task["drive"],
        is_cyclic=task["is_cyclic"] if task["drive"] == "start" else 0,
        priority=task["priority"], note=task["note"], created=now(),
        deadline=deadline, anchor=anchor,
        expected_duration=sched["expected_duration"],
        recurrence_interval=sched["recurrence_interval"],
        tags=[r["name"] for r in conn.execute(
            "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id"
            " WHERE tt.task_id=?", (task["id"],)).fetchall()],
    )


def do_done(conn, p):
    """完成任务(-> done)。周期任务克隆下一个实例。cyclic 返回是否克隆了。"""
    tid = p["task_id"]
    task = db.get_task(conn, tid)
    if not task:
        return {"error": "task not found"}
    cloned = False
    if task["drive"] == "start" and task["is_cyclic"]:
        # start 周期:锚点重置为 now
        _clone_next(conn, task, anchor=now())
        cloned = True
    elif task["drive"] == "end":
        sched = conn.execute("SELECT deadline, recurrence_interval FROM schedule WHERE task_id=?",
                             (tid,)).fetchone()
        if sched["recurrence_interval"] and sched["deadline"] is not None:
            # end 周期:deadline 顺延一个间隔(精确保留时分)
            _clone_next(conn, task,
                        deadline=int(sched["deadline"]) + int(sched["recurrence_interval"]))
            cloned = True
    db.set_status(conn, tid, "done")
    return {"task_id": tid, "done": True, "cyclic": cloned}


def close_overdue(conn, now=None):
    """把已过 deadline 的 active end 任务置为 closed(超时即结束)。

    周期任务(recurrence_interval 非空)同时克隆下一个实例(deadline 顺延)。
    返回关闭的任务数。在 engine.today_lists / pusher.tick_push 入口调用。
    """
    now = now if now is not None else now_ts()
    rows = conn.execute(
        "SELECT t.*, s.deadline, s.recurrence_interval FROM tasks t"
        " JOIN schedule s ON s.task_id=t.id"
        " WHERE t.drive='end' AND t.status='active'"
        " AND s.deadline IS NOT NULL AND s.deadline < ?",
        (now,)).fetchall()
    for task in rows:
        if task["recurrence_interval"]:
            _clone_next(conn, task,
                        deadline=int(task["deadline"]) + int(task["recurrence_interval"]))
        db.set_status(conn, task["id"], "closed")
    return len(rows)


def do_update(conn, p):
    tid = p["task_id"]
    fields, args = [], []
    for k in ("title", "note", "priority", "is_cyclic"):
        if k in p:
            fields.append(f"{k}=?")
            args.append(p[k])
    if fields:
        with conn:
            conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", (*args, tid))
    # schedule 字段
    sfields, sargs = [], []
    for k in ("deadline", "anchor", "expected_duration", "recurrence_interval"):
        if k in p:
            sfields.append(f"{k}=?")
            sargs.append(p[k])
    if sfields:
        with conn:
            conn.execute(f"UPDATE schedule SET {', '.join(sfields)} WHERE task_id=?", (*sargs, tid))
    return {"task_id": tid, "updated": True}


def do_close(conn, p):
    db.set_status(conn, p["task_id"], "closed")
    return {"task_id": p["task_id"], "closed": True}


def do_snooze(conn, p):
    """推迟任务。p 可带 until(Unix 秒,绝对时间点);缺省按 1 小时。

    写 push_log + 记 tasks.snooze_until,冷却判断统一读 snooze_until(见 pusher)。
    """
    tid = p["task_id"]
    until = p.get("until") or (now() + 3600)
    db.set_snooze(conn, tid, until)
    db.log_push(conn, tid, now(), "snoozed", response="snoozed")
    return {"task_id": tid, "snoozed": True, "until": until}


def snooze_options():
    """推迟预设选项:{key: (显示名, 到点的 Unix 秒)}。自定义由调用方传绝对 ts。

    - 1h / 3h:从 now 往后推
    - tomorrow:次日 08:00
    - next_week:下周一 08:00
    """
    from datetime import datetime, timedelta
    t = now()
    dt = datetime.fromtimestamp(t)

    def at(d, hour=8):
        return int(d.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp())

    tomorrow = dt + timedelta(days=1)
    # 下周一:本周一 + 7 天
    monday = dt - timedelta(days=dt.weekday()) + timedelta(days=7)
    return {
        "1h": ("1 小时后", t + 3600),
        "3h": ("3 小时后", t + 3 * 3600),
        "tomorrow": ("明天", at(tomorrow)),
        "next_week": ("下周", at(monday)),
    }


def do_query(conn, p):
    rows = db.list_active(conn, p.get("drive"))
    tag = p.get("tag")
    out = []
    for r in rows:
        if tag:
            tagnames = [x["name"] for x in conn.execute(
                "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id"
                " WHERE tt.task_id=?", (r["id"],)).fetchall()]
            if tag not in tagnames:
                continue
        n, last = db.push_stats(conn, r["id"])
        out.append({"id": r["id"], "title": r["title"], "drive": r["drive"],
                    "deadline": r["deadline"], "anchor": r["anchor"],
                    "expected_duration": r["expected_duration"],
                    "recurrence_interval": r["recurrence_interval"],
                    "priority": r["priority"], "nag_count": n})
    return {"tasks": out}
