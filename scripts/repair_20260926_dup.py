# 一次性修复脚本:清掉 2026-09-26 报告的每日任务重复数据。
#
# 事故链(见 tests/core/test_dup_repro.py):do_done 无状态守卫,跨天
# close_overdue 关旧克隆新后,浮窗残留卡上的「完成」再打到已关闭任务上,
# 又克隆一份;此后每天午夜按份克隆,N 份永不收敛。「日语每日(和豆包)」
# 已累积 3 份 active(09-20 与 09-23 两次 1->2 跳变所致)。
#
# 与 08-28 那次不同:根因已在本次一并修复(do_done 原子认领 + closed 事件撤卡),
# 本脚本只清数据。处置用 status='closed' 不删行(可回溯,push_log 关联保留);
# 备份:data/assistant.db.bak5(修复前快照,sqlite backup API,运行中拷贝安全)。
import sqlite3

DB = r"C:/Users/Dao/Code/dao1023/claude-assistant/data/assistant.db"

# 每标题保留哪一份 active(explicit > clever:只动确认过的重复)
KEEP = {"日语每日(和豆包)": "e9b26d1d890c"}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

for title, keep_id in KEEP.items():
    rows = conn.execute(
        "SELECT id, created FROM tasks WHERE title=? AND status='active' ORDER BY created",
        (title,)).fetchall()
    drop = [r["id"] for r in rows if r["id"] != keep_id]
    print(f"{title}: active 共 {len(rows)} 份,保留 {keep_id}(最早),关闭 {drop}")

    with conn:
        q = ",".join("?" * len(drop))
        conn.execute(f"UPDATE tasks SET status='closed' WHERE id IN ({q})", drop)

# ---- 验证:全库同名多 active 应为 0 组;过期 active 应为 0 条 ----
left = conn.execute(
    "SELECT title, COUNT(*) n FROM tasks WHERE status='active'"
    " GROUP BY title HAVING n>1").fetchall()
print("修后同名多 active 组:", [dict(r) for r in left] or "无")

overdue = conn.execute(
    "SELECT t.id, t.title, s.deadline FROM tasks t JOIN schedule s ON s.task_id=t.id"
    " WHERE t.status='active' AND t.drive='end' AND s.deadline IS NOT NULL"
    " AND s.deadline < strftime('%s','now')").fetchall()
print("仍过期的 active end:", [dict(r) for r in overdue] or "无")

conn.close()
