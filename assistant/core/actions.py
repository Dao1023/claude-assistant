"""任务动作:任务的增/完成/改/关/稍后/查,操作 SQLite。

属于 core 层:纯任务逻辑,不碰弹窗/唤起/HTTP。
调用方:HTTP 接口(io/server.py)、催办小卡(io/pusher.py)。
时间字段内部一律 Unix 秒级 int(见 core/timeutil.py)。
"""
from . import db
from .timeutil import SECONDS_PER_DAY, now_ts


def now():
    """当前 Unix 秒级时间戳(写 created / pushed_at 用)。"""
    return now_ts()


# ---------- 各动作 ----------

def do_add(conn, p):
    anchor = p.get("anchor") or (now() if p.get("drive") == "start" else None)
    tid = db.add_task(
        conn,
        title=p["title"],
        drive=p["drive"],
        is_cyclic=p.get("is_cyclic", 0),
        priority=p.get("priority", 3),
        note=p.get("note"),
        created=now(),
        deadline=p.get("deadline"),
        anchor=anchor,
        cycle_days=p.get("cycle_days"),
        tags=p.get("tags", []),
    )
    return {"task_id": tid, "title": p["title"]}


def do_done(conn, p):
    """完成任务。周期任务克隆下一个(anchor/deadline 顺延,推送计数随新任务自然清零)。"""
    tid = p["task_id"]
    task = db.get_task(conn, tid)
    if not task:
        return {"error": "task not found"}
    if task["is_cyclic"]:
        sched = conn.execute("SELECT * FROM schedule WHERE task_id=?", (tid,)).fetchone()
        cycle = sched["cycle_days"] or 1
        # 克隆下一个:start 锚点重置为现在;end 截止按周期秒级顺延(精确保留时分,如"次日 4:00")
        new_anchor = now() if task["drive"] == "start" else None
        new_deadline = None
        if task["drive"] == "end" and sched["deadline"] is not None:
            new_deadline = int(sched["deadline"]) + cycle * SECONDS_PER_DAY
        db.add_task(conn, task["title"], task["drive"], is_cyclic=1,
                    priority=task["priority"], note=task["note"], created=now(),
                    deadline=new_deadline, anchor=new_anchor, cycle_days=cycle,
                    tags=[r["name"] for r in conn.execute(
                        "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id"
                        " WHERE tt.task_id=?", (tid,)).fetchall()])
    db.set_status(conn, tid, "done")
    return {"task_id": tid, "done": True, "cyclic": bool(task["is_cyclic"])}


def do_update(conn, p):
    tid = p["task_id"]
    fields, args = [], []
    for k in ("title", "note", "priority"):
        if k in p:
            fields.append(f"{k}=?")
            args.append(p[k])
    if fields:
        with conn:
            conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", (*args, tid))
    # schedule 字段
    sfields, sargs = [], []
    for k in ("deadline", "anchor", "cycle_days"):
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
    db.log_push(conn, p["task_id"], now(), "snoozed", response="snoozed")
    return {"task_id": p["task_id"], "snoozed": True}


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
                    "cycle_days": r["cycle_days"], "priority": r["priority"], "nag_count": n})
    return {"tasks": out}
