"""一次性迁移:把存量时间字段从字符串('YYYY-MM-DD[ HH:MM[:SS]]')迁到 Unix 秒级 int。

涉及字段:
- tasks.created
- schedule.deadline / schedule.anchor
- push_log.pushed_at

幂等:已是 INTEGER 的行跳过,重复运行安全。运行前自动备份 assistant.db -> assistant.db.bak。

用法:
    uv run python scripts/migrate_unix_time.py
"""
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assistant import config
from assistant.core.timeutil import to_ts

# (表, 时间字段列) —— 只迁这些列
COLUMNS = [
    ("tasks", ["created"]),
    ("schedule", ["deadline", "anchor"]),
    ("push_log", ["pushed_at"]),
]


def _is_text(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        print(f"数据库不存在,无需迁移: {db_path}")
        return

    backup = db_path.with_suffix(".db.bak")
    shutil.copy2(db_path, backup)
    print(f"已备份: {backup}")

    conn = sqlite3.connect(db_path)
    try:
        total = 0
        for table, cols in COLUMNS:
            # 表可能不存在(旧库),查一下
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            for col in cols:
                rows = conn.execute(f"SELECT rowid, {col} FROM {table}").fetchall()
                for rowid, val in rows:
                    if _is_text(val):
                        ts = to_ts(val)
                        conn.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (ts, rowid))
                        total += 1
        conn.commit()
        print(f"迁移完成,共转换 {total} 个时间字段为 Unix 秒。")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(config.DB_PATH)
