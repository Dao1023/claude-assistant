"""SQLite 数据库层:建表 + 连接 + 基础 CRUD。

表结构见 docs/schema.md。所有时间字段内部一律 Unix 秒级整数(INTEGER);
边界字符串与 int 的互转在 core/timeutil.py,由 server/queries 在出入口处理。
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
  created     INTEGER NOT NULL,           -- 创建时间,Unix 秒
  snooze_until INTEGER                    -- 推迟到此时间(Unix 秒),NULL=未推迟
);

CREATE TABLE IF NOT EXISTS schedule (
  task_id             TEXT PRIMARY KEY REFERENCES tasks(id),
  deadline            INTEGER,   -- end 驱动:截止时间,Unix 秒
  anchor              INTEGER,   -- start 驱动:上次完成时间,Unix 秒
  expected_duration   INTEGER,   -- start 驱动:预期间隔(重要性归一化分母),秒
  recurrence_interval INTEGER    -- end 驱动:重复间隔,秒;NULL=非周期
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
  pushed_at  INTEGER NOT NULL,      -- 推送时间,Unix 秒
  stage      TEXT,
  response   TEXT,
  note       TEXT                    -- 用户留言:完成/推迟时顺手记的「为什么」
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
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
        _migrate(conn)


def _migrate(conn):
    """轻量迁移:老库缺列时 ALTER 补上(新库由 SCHEMA 直接含,跳过)。

    判据:PRAGMA table_info 看列在不在,幂等。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(push_log)")}
    if "note" not in cols:
        conn.execute("ALTER TABLE push_log ADD COLUMN note TEXT")


def new_id():
    return uuid.uuid4().hex[:12]


# ---------- tasks ----------

def add_task(conn, title, drive, is_cyclic=0, priority=3, note=None,
             created=None, deadline=None, anchor=None,
             expected_duration=None, recurrence_interval=None, tags=()):
    """插入任务 + schedule + tag 关联,返回 task id。

    start 驱动用 anchor + expected_duration;end 驱动用 deadline + recurrence_interval。
    """
    tid = new_id()
    with conn:
        conn.execute(
            "INSERT INTO tasks (id,title,note,drive,is_cyclic,priority,status,created)"
            " VALUES (?,?,?,?,?,?,'active',?)",
            (tid, title, note, drive, is_cyclic, priority, created),
        )
        conn.execute(
            "INSERT INTO schedule (task_id,deadline,anchor,expected_duration,recurrence_interval)"
            " VALUES (?,?,?,?,?)",
            (tid, deadline, anchor, expected_duration, recurrence_interval),
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


def set_tags(conn, tid, tags):
    """覆盖式更新任务的 tag 关联:先清旧关联,再按给定名字逐个挂接(自动建缺失 tag)。"""
    with conn:
        conn.execute("DELETE FROM task_tags WHERE task_id=?", (tid,))
        for name in tags:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO task_tags (task_id,tag_id) VALUES (?,?)",
                (tid, row["id"]),
            )


def set_status(conn, tid, status):
    with conn:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))


def set_snooze(conn, tid, until_ts):
    """设置/清除任务的推迟时间(Unix 秒,None=清除)。"""
    with conn:
        conn.execute("UPDATE tasks SET snooze_until=? WHERE id=?", (until_ts, tid))


def list_active(conn, drive=None):
    sql = ("SELECT t.*, s.deadline, s.anchor, s.expected_duration, s.recurrence_interval"
           " FROM tasks t JOIN schedule s ON s.task_id=t.id WHERE t.status='active'")
    args = []
    if drive:
        sql += " AND t.drive=?"
        args.append(drive)
    return conn.execute(sql, args).fetchall()


# ---------- push_log ----------

def log_push(conn, tid, pushed_at, stage, response=None, note=None):
    with conn:
        conn.execute(
            "INSERT INTO push_log (task_id,pushed_at,stage,response,note) VALUES (?,?,?,?,?)",
            (tid, pushed_at, stage, response, note),
        )


def push_stats(conn, tid):
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(pushed_at) AS last_at FROM push_log WHERE task_id=?",
        (tid,),
    ).fetchone()
    return row["n"], row["last_at"]


# ---------- settings ----------

def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn, key, value):
    with conn:
        conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def all_settings(conn):
    return {r["key"]: r["value"]
            for r in conn.execute("SELECT key,value FROM settings").fetchall()}
