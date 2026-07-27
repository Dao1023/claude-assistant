"""SQLite 数据库层:建表 + 连接 + 基础 CRUD。

表结构见 docs/schema.md。所有时间用 ISO 字符串(YYYY-MM-DD 或 YYYY-MM-DD HH:MM)。
"""
import sqlite3
import uuid

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  note        TEXT,
  drive       TEXT NOT NULL,              -- 'start' / 'end'
  is_cyclic   INTEGER NOT NULL DEFAULT 0,
  priority    INTEGER NOT NULL DEFAULT 3,
  status      TEXT NOT NULL DEFAULT 'active',
  created     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule (
  task_id     TEXT PRIMARY KEY REFERENCES tasks(id),
  deadline    TEXT,
  anchor      TEXT,
  cycle_days  INTEGER
);

CREATE TABLE IF NOT EXISTS tags (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS task_tags (
  task_id TEXT REFERENCES tasks(id),
  tag_id  INTEGER REFERENCES tags(id),
  PRIMARY KEY (task_id, tag_id)
);

CREATE TABLE IF NOT EXISTS push_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT REFERENCES tasks(id),
  pushed_at  TEXT NOT NULL,
  stage      TEXT,
  response   TEXT
);
"""


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def new_id():
    return uuid.uuid4().hex[:12]


# ---------- tasks ----------

def add_task(conn, title, drive, is_cyclic=0, priority=3, note=None,
             created=None, deadline=None, anchor=None, cycle_days=None, tags=()):
    """插入任务 + schedule + tag 关联,返回 task id。"""
    tid = new_id()
    with conn:
        conn.execute(
            "INSERT INTO tasks (id,title,note,drive,is_cyclic,priority,status,created)"
            " VALUES (?,?,?,?,?,?,'active',?)",
            (tid, title, note, drive, is_cyclic, priority, created),
        )
        conn.execute(
            "INSERT INTO schedule (task_id,deadline,anchor,cycle_days) VALUES (?,?,?,?)",
            (tid, deadline, anchor, cycle_days),
        )
        for name in tags:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO task_tags (task_id,tag_id) VALUES (?,?)",
                (tid, row["id"]),
            )
    return tid


def get_task(conn, tid):
    return conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()


def set_status(conn, tid, status):
    with conn:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))


def list_active(conn, drive=None):
    sql = ("SELECT t.*, s.deadline, s.anchor, s.cycle_days FROM tasks t"
           " JOIN schedule s ON s.task_id=t.id WHERE t.status='active'")
    args = []
    if drive:
        sql += " AND t.drive=?"
        args.append(drive)
    return conn.execute(sql, args).fetchall()


# ---------- push_log ----------

def log_push(conn, tid, pushed_at, stage, response=None):
    with conn:
        conn.execute(
            "INSERT INTO push_log (task_id,pushed_at,stage,response) VALUES (?,?,?,?)",
            (tid, pushed_at, stage, response),
        )


def push_stats(conn, tid):
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(pushed_at) AS last_at FROM push_log WHERE task_id=?",
        (tid,),
    ).fetchone()
    return row["n"], row["last_at"]
