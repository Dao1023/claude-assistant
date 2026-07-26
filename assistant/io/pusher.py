"""推送生命周期:按重要性挑任务,三档催促 + 节流 + 冷却,写 push_log。

属于 io 层:直接调 notifier 弹窗(不借道 inbox.json,避免触发 watcher 连锁)。
"""
from datetime import datetime

from ..core import db, engine
from .notifier import notify_task

MAX_CONCURRENT = 3        # 同时最多催几个(节流)
COOLDOWN_SEC = 3600       # 同一任务推送冷却(秒):距上次不足则跳过
ESCALATE_NAGS = 3         # 被推几次后升级档位


def _stage(task, nag_count):
    """根据任务与已推次数定档位。"""
    if task["drive"] == "end":
        if engine.end_importance(task["deadline"]) >= engine.OVERDUE:
            return "crisis"
        if nag_count >= ESCALATE_NAGS:
            return "escalating"
    else:
        if nag_count >= ESCALATE_NAGS * 2:
            return "escalating"
    return "gentle"


def _cooling_down(last_at):
    """距上次推送不足冷却时间则返回 True。"""
    if not last_at:
        return False
    try:
        last = datetime.strptime(last_at, "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return (datetime.now() - last).total_seconds() < COOLDOWN_SEC


def tick_push():
    """主入口:算重要性 → 挑 top N(冷却过滤)→ 推送并记录。返回推送数。"""
    conn = db.connect()
    db.init_db()
    ends, starts = engine.today_lists(conn)
    candidates = ends + starts           # end 优先,再 start(均已排序)
    pushed = 0
    for task in candidates:
        if pushed >= MAX_CONCURRENT:
            break
        nag_count, last_at = db.push_stats(conn, task["id"])
        if _cooling_down(last_at):       # 冷却期内跳过
            continue
        stage = _stage(task, nag_count)
        notify_task(task, stage)
        db.log_push(conn, task["id"], datetime.now().strftime("%Y-%m-%d %H:%M"), stage)
        pushed += 1
    conn.close()
    return pushed
