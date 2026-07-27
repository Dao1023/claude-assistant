"""推送生命周期:按重要性挑任务,三档催促 + 节流 + 冷却,弹催办小卡 + 写 push_log。

属于 io 层:弹 tkinter 小卡(popup),按钮接生命周期(完成/稍后/找AI)。
时间一律 Unix 秒级 int(core/timeutil.py)。
"""
from ..core import actions, db, engine
from ..core.timeutil import now_ts, to_str
from .launcher import launch_claude
from .popup import show_task_card

MAX_CONCURRENT = 3        # 同时最多催几个(节流)
COOLDOWN_SEC = 3600       # 同一任务推送冷却(秒):距上次不足则跳过
ESCALATE_NAGS = 3         # 被推几次后升级档位
CRISIS_IMPORTANCE = 1.0   # end 重要性到此值(约剩 9 小时内)升级为 crisis


def _stage(task, nag_count):
    """根据任务与已推次数定档位。end 临近截止升级为 crisis(过期任务已被关闭,不在此列)。"""
    if task["drive"] == "end":
        if engine.end_importance(task["deadline"]) >= CRISIS_IMPORTANCE:
            return "crisis"
        if nag_count >= ESCALATE_NAGS:
            return "escalating"
    else:
        if nag_count >= ESCALATE_NAGS * 2:
            return "escalating"
    return "gentle"


def _cooling_down(last_at):
    """距上次推送不足冷却时间则返回 True。last_at 为 Unix 秒级 int(None 表示没推过)。"""
    if not last_at:
        return False
    return (now_ts() - int(last_at)) < COOLDOWN_SEC


def _now():
    """写 push_log 用的当前 Unix 秒级时间戳。"""
    return now_ts()


def _make_callbacks(tid):
    """三个按钮的真实生命周期操作。"""
    def on_done():
        conn = db.connect()
        actions.do_done(conn, {"task_id": tid})       # 周期任务自动克隆下一个
        db.log_push(conn, tid, _now(), "done", response="done")
        conn.close()

    def on_snooze():
        conn = db.connect()
        db.log_push(conn, tid, _now(), "snoozed", response="snoozed")
        conn.close()

    def on_ai():
        launch_claude()                                 # 只开干净窗口,用户自己 /resume

    return on_done, on_snooze, on_ai


def tick_push():
    """主入口:算重要性 → 挑 top N(冷却过滤)→ 弹小卡并记录。返回推送数。"""
    conn = db.connect()
    db.init_db()
    actions.close_overdue(conn)            # 超时即关闭:过期 end 任务先落 closed
    ends, starts = engine.today_lists(conn)
    candidates = ends + starts           # end 优先,再 start(均已排序)
    tasks = []
    for task in candidates:
        if len(tasks) >= MAX_CONCURRENT:
            break
        nag_count, last_at = db.push_stats(conn, task["id"])
        if _cooling_down(last_at):       # 冷却期内跳过
            continue
        stage = _stage(task, nag_count)
        db.log_push(conn, task["id"], _now(), stage)
        tasks.append((task, stage))
    conn.close()

    for task, stage in tasks:
        on_done, on_snooze, on_ai = _make_callbacks(task["id"])
        show_task_card(task, stage, on_done, on_snooze, on_ai)
        print(f"[{to_str(_now())}] 弹小卡: [{stage}] {task['title']}")
    return len(tasks)
