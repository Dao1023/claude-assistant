"""推送生命周期:按重要性挑任务,三档催促 + 节流 + 冷却,弹催办小卡 + 写 push_log。

属于 io 层:弹 tkinter 小卡(popup),按钮接生命周期(完成/稍后/找AI)。
时间一律 Unix 秒级 int(core/timeutil.py)。
过滤/定档逻辑走 core/funnel 管线(与规则页 /api/funnel 统计共用同一份,保证一致);
数值阈值读 core/settings,可在规则页配置。
"""
from ..core import actions, db, funnel, settings
from ..core.timeutil import now_ts, to_str
from .launcher import launch_claude
from .popup import show_task_card


def _now():
    """写 push_log 用的当前 Unix 秒级时间戳。"""
    return now_ts()


def _make_callbacks(tid):
    """三个按钮的真实生命周期操作。on_snooze 接受可选 until(秒)。"""
    def on_done():
        conn = db.connect()
        actions.do_done(conn, {"task_id": tid})       # 周期任务自动克隆下一个
        db.log_push(conn, tid, _now(), "done", response="done")
        conn.close()

    def on_snooze(until=None):
        conn = db.connect()
        actions.do_snooze(conn, {"task_id": tid, "until": until})
        conn.close()

    def on_ai():
        launch_claude()                                 # 只开干净窗口,用户自己 /resume

    return on_done, on_snooze, on_ai


def pick(conn, now=None):
    """挑本轮该催的任务(不写库、不弹卡,纯选择,供 tick_push 与 /api/funnel 共用)。

    返回 (picked, blocked):picked 是 [(task, stage, nag_count)];blocked 是
    {layer_id: [(task, reason)]},记录每个任务被挡在哪一层(只算第一层)。
    调用方须先跑 actions.close_overdue,确保过期 end 已关闭、不在此列。
    """
    now = now if now is not None else _now()
    ends, starts = funnel_engine_lists(conn)
    limit = settings.get("max_concurrent")

    picked, blocked = [], {}

    # 免打扰总闸:夜间或手动 DND 命中 → 整条线冻结,所有任务挡在 dnd 层
    dnd_reason = funnel.dnd_active(now)
    if dnd_reason is not None:
        for task in ends + starts:
            blocked.setdefault("dnd", []).append((task, dnd_reason))
        return picked, blocked

    survivors = []
    for task in ends + starts:                       # end 优先,再 start(均已排序)
        nag_count, last_at = db.push_stats(conn, task["id"])
        ctx = funnel.make_ctx(now=now, last_at=last_at)
        layer_id, reason = funnel.run_pipe(task, ctx)
        if layer_id is not None:
            blocked.setdefault(layer_id, []).append((task, reason))
            continue
        survivors.append((task, nag_count))

    # 限量层:幸存者按序截断到 max_concurrent,其余算被「限量」挡
    for task, nag_count in survivors[:limit]:
        picked.append((task, funnel.stage(task, nag_count), nag_count))
    for task, _ in survivors[limit:]:
        blocked.setdefault("limit", []).append((task, "本轮名额已满,排队下轮"))

    return picked, blocked


def funnel_engine_lists(conn):
    """取今日清单(end 按剩余升序,start 按重要性降序)。薄封装便于测试替换。"""
    from ..core import engine
    return engine.today_lists(conn)


def tick_push():
    """主入口:挑本轮最该催的(end 优先)→ 弹小卡并写 push_log。"""
    conn = db.connect()
    db.init_db()
    actions.close_overdue(conn)            # 超时即关闭:过期 end 任务先落 closed
    now = _now()
    picked, _blocked = pick(conn, now)
    for task, stage, _nag in picked:
        db.log_push(conn, task["id"], now, stage)
    conn.close()

    for task, stage, _nag in picked:
        on_done, on_snooze, on_ai = _make_callbacks(task["id"])
        show_task_card(task, stage, on_done, on_snooze, on_ai)
        print(f"[{to_str(now)}] 弹小卡: [{stage}] {task['title']}")
    return len(picked)
