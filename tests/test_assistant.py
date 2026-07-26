"""测试:数据库、指令、重要性算法、推送逻辑。用临时 DB,不碰正式数据。"""
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 用临时数据库
_tmp = tempfile.mkdtemp()
os.environ.setdefault("TEST", "1")
from assistant import config
config.DB_PATH = Path(_tmp) / "test.db"

from assistant.core import commands, db, engine

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


_n = [0]


def fresh():
    """每次用独立 DB 文件,避免 Windows 文件锁。"""
    _n[0] += 1
    config.DB_PATH = Path(_tmp) / f"test_{_n[0]}.db"
    db.init_db()
    return db.connect()


# ---------- 重要性算法 ----------
print("\n[重要性算法]")
today = datetime.now().date()

# start: x=1 → 0;x>1 → 正;x<1 → 负;x=0 → -inf
check("start x=1 → 0", engine.start_importance(str(today - timedelta(days=30)), 30) == 0)
check("start x=2 → log2>0", engine.start_importance(str(today - timedelta(days=60)), 30) > 0)
check("start x=0.5 → 负", engine.start_importance(str(today - timedelta(days=15)), 30) < 0)
check("start 当天 → -inf", engine.start_importance(str(today), 30) == float("-inf"))

# end: 剩多→负,剩少→正,过期→OVERDUE
check("end 剩30天 → -log30<0", engine.end_importance(str(today + timedelta(days=30))) < 0)
check("end 剩1天 → 0", engine.end_importance(str(today + timedelta(days=1))) == 0)
check("end 已过期 → OVERDUE", engine.end_importance(str(today - timedelta(days=1))) == engine.OVERDUE)

# end 越近越急(单调)
i_far = engine.end_importance(str(today + timedelta(days=30)))
i_near = engine.end_importance(str(today + timedelta(days=2)))
check("end 越近重要性越大", i_near > i_far)

# start 越久重要性越大但放缓(对数)
s1 = engine.start_importance(str(today - timedelta(days=30)), 30)
s2 = engine.start_importance(str(today - timedelta(days=300)), 30)
check("start 越久越大", s2 > s1)

# 归一化:体检(365)不会像纯时长那样霸榜
ti_jian = engine.start_importance(str(today - timedelta(days=200)), 365)  # x<1
friend = engine.start_importance(str(today - timedelta(days=60)), 30)      # x=2
check("体检200天(x<1) < 看朋友60天(x=2)", ti_jian < friend)


# ---------- 数据库 + 指令 ----------
print("\n[数据库与指令]")
conn = fresh()

# add
r = commands.do_add(conn, {"title": "原神每日", "drive": "end", "is_cyclic": 1,
                           "cycle_days": 1, "deadline": str(today) + " 23:59", "tags": ["genshin"]})
check("add end 周期任务", "task_id" in r)
tid = r["task_id"]
check("任务入库", db.get_task(conn, tid)["title"] == "原神每日")

# tag 关联
tags = [x["name"] for x in conn.execute(
    "SELECT g.name FROM tags g JOIN task_tags tt ON tt.tag_id=g.id WHERE tt.task_id=?", (tid,))]
check("tag 关联成功", "genshin" in tags)

# done 周期任务 → 克隆
before = len(db.list_active(conn, "end"))
r = commands.do_done(conn, {"task_id": tid})
after = len(db.list_active(conn, "end"))
check("done 周期任务后克隆新任务", after == before and r["cyclic"])
check("原任务标记 done", db.get_task(conn, tid)["status"] == "done")

# start 周期任务 done → anchor 重置为今天
conn2 = fresh()
r = commands.do_add(conn2, {"title": "看发小", "drive": "start", "is_cyclic": 1,
                            "cycle_days": 30, "anchor": "2026-06-01"})
tid2 = r["task_id"]
commands.do_done(conn2, {"task_id": tid2})
new = [x for x in db.list_active(conn2, "start")][0]
check("start 周期克隆后 anchor=今天", new["anchor"] == str(today))

# query
conn3 = fresh()
commands.do_add(conn3, {"title": "任务A", "drive": "end", "deadline": str(today), "tags": ["公司"]})
commands.do_add(conn3, {"title": "任务B", "drive": "end", "deadline": str(today), "tags": ["genshin"]})
q = commands.do_query(conn3, {"tag": "genshin"})
check("query 按 tag 筛选", len(q["tasks"]) == 1 and q["tasks"][0]["title"] == "任务B")


# ---------- 指令文件处理 ----------
print("\n[commands.json 处理]")
conn4 = fresh()
config.COMMANDS = Path(_tmp) / "commands.json"
config.COMMANDS.write_text('{"commands": [{"id":"c1","action":"add","status":"pending",'
                           '"payload":{"title":"测试任务","drive":"end","deadline":"%s"}}]}' % (str(today) + " 18:00"),
                           encoding="utf-8")
n = commands.process_commands()
check("process_commands 处理 1 条", n == 1)
data = __import__("json").loads(config.COMMANDS.read_text(encoding="utf-8"))
check("指令回写 processed + result", data["commands"][0]["status"] == "processed"
      and "task_id" in data["commands"][0]["result"])


# ---------- 推送统计 ----------
print("\n[推送统计]")
conn5 = fresh()
r = commands.do_add(conn5, {"title": "推送测试", "drive": "end", "deadline": str(today)})
tid5 = r["task_id"]
db.log_push(conn5, tid5, "2026-07-27 10:00", "gentle")
db.log_push(conn5, tid5, "2026-07-27 12:00", "escalating")
n, last = db.push_stats(conn5, tid5)
check("push_stats 计数=2", n == 2)
check("push_stats last_at 取最大", last == "2026-07-27 12:00")


print(f"\n{'='*40}\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
