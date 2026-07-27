"""一次性迁移:tasks 表加 snooze_until 列(推迟截止时间,Unix 秒,可空)。

幂等:列已存在则跳过。运行前自动备份 .db.bak3。

用法:
    uv run python scripts/migrate_snooze.py
"""
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assistant import config


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        print(f"数据库不存在,无需迁移: {db_path}")
        return

    backup = db_path.with_suffix(".db.bak3")
    shutil.copy2(db_path, backup)
    print(f"已备份: {backup}")

    conn = sqlite3.connect(db_path)
    try:
        has = any(r[1] == "snooze_until" for r in conn.execute("PRAGMA table_info(tasks)"))
        if has:
            print("snooze_until 列已存在,跳过。")
        else:
            conn.execute("ALTER TABLE tasks ADD COLUMN snooze_until INTEGER")
            conn.commit()
            print("加列: tasks.snooze_until")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(config.DB_PATH)
