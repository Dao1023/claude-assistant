"""指令解析:读 commands.json,执行 add/done/update/close/snooze/query,操作 SQLite。

属于 core 层:纯任务逻辑,不碰弹窗/唤起。文件读写经 config.COMMANDS。
"""
import json
from datetime import datetime, timedelta

from .. import config
from . import db


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today():
    return datetime.now().strftime("%Y-%m-%d")


# ---------- commands.json 读写 ----------

def load_commands():
    try:
        return json.loads(config.COMMANDS.read_text(encoding="utf-8"))
    except Exception:
        return {"commands": []}


def save_commands(data):
    config.COMMANDS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 各 action ----------

def do_add(conn, p):
    anchor = p.get("anchor") or (today() if p.get("drive") == "start" else None)
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
        # 克隆下一个
        new_anchor = today() if task["drive"] == "start" else None
        new_deadline = None
        if task["drive"] == "end" and sched["deadline"]:
            d = datetime.strptime(sched["deadline"], "%Y-%m-%d %H:%M") + timedelta(days=cycle)
            new_deadline = d.strftime("%Y-%m-%d %H:%M")
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


ACTIONS = {"add": do_add, "done": do_done, "update": do_update,
           "close": do_close, "snooze": do_snooze, "query": do_query}


def process_commands():
    """处理所有 pending 指令,回写结果。返回处理数。"""
    data = load_commands()
    conn = db.connect()
    db.init_db()
    n = 0
    for cmd in data["commands"]:
        if cmd.get("status") != "pending":
            continue
        fn = ACTIONS.get(cmd["action"])
        if not fn:
            cmd["status"], cmd["result"] = "error", {"error": "unknown action"}
            continue
        try:
            cmd["result"] = fn(conn, cmd.get("payload", {}))
            cmd["status"] = "processed"
            n += 1
        except Exception as e:
            cmd["status"], cmd["result"] = "error", {"error": str(e)}
    conn.close()
    if n:
        save_commands(data)
    return n
