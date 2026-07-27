"""一次性迁移:schedule.cycle_days 拆分为 start/end 各自的秒级字段。

- start 任务:cycle_days -> expected_duration(秒),预期间隔(归一化分母)
- end 任务:cycle_days -> recurrence_interval(秒),重复间隔;并清空 is_cyclic(end 不用)
- 一次性 start 任务(历史遗留 is_cyclic=1 但实为一次性)需人工/另行修正,本脚本只做字段拆分

幂等:新列已存在则跳过加列;cycle_days 为空则跳过该行。运行前自动备份 .db.bak2。

用法:
    uv run python scripts/migrate_split_fields.py
"""
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assistant import config
from assistant.core.timeutil import SECONDS_PER_DAY


def _has_column(conn, table, col) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        print(f"数据库不存在,无需迁移: {db_path}")
        return

    backup = db_path.with_suffix(".db.bak2")
    shutil.copy2(db_path, backup)
    print(f"已备份: {backup}")

    conn = sqlite3.connect(db_path)
    try:
        # 1. 加新列(幂等)
        for col in ("expected_duration", "recurrence_interval"):
            if not _has_column(conn, "schedule", col):
                conn.execute(f"ALTER TABLE schedule ADD COLUMN {col} INTEGER")
                print(f"加列: schedule.{col}")

        if not _has_column(conn, "schedule", "cycle_days"):
            print("无 cycle_days 列,可能已迁移过。")
        else:
            # 2. 按 drive 拆分 cycle_days -> 新字段(转秒)
            rows = conn.execute(
                "SELECT s.task_id, t.drive, s.cycle_days FROM schedule s"
                " JOIN tasks t ON t.id = s.task_id"
            ).fetchall()
            n = 0
            for task_id, drive, cycle_days in rows:
                if cycle_days is None:
                    continue
                secs = cycle_days * SECONDS_PER_DAY
                if drive == "start":
                    conn.execute(
                        "UPDATE schedule SET expected_duration=? WHERE task_id=?",
                        (secs, task_id))
                else:  # end
                    conn.execute(
                        "UPDATE schedule SET recurrence_interval=? WHERE task_id=?",
                        (secs, task_id))
                    # end 不用 is_cyclic,清空
                    conn.execute(
                        "UPDATE tasks SET is_cyclic=0 WHERE id=?", (task_id,))
                n += 1
            print(f"拆分 {n} 行 cycle_days -> expected_duration/recurrence_interval(秒)")

        conn.commit()
        print("迁移完成。")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate(config.DB_PATH)
