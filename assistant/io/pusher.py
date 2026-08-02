"""推送生命周期:按重要性挑任务,三档催促 + 节流 + 冷却,弹催办小卡 + 写 push_log。

属于 io 层:弹 tkinter 小卡(popup),按钮接生命周期(完成/稍后/找AI)。
时间一律 Unix 秒级 int(core/timeutil.py)。
数值阈值(冷却系数/兜底/升级次数/危机阈值/最多弹卡)读 core/settings,可在规则页配置。
"""
from ..core import actions, db, engine, settings
from ..core.timeutil import now_ts, to_str
from .launcher import launch_claude
from .popup import show_task_card


def _task_interval(task):
    """任务的间隔(秒):start 用 expected_duration,end 用 recurrence_interval。无则 None。"""
    if task["drive"] == "start":
        return task.get("expected_duration")
    return task.get("recurrence_interval")


def _is_future_period(task, now=None):
    """周期 end 任务是否还轮不到(剩余 > 一个周期,是明天/后天那份)。

    每日 4 点重置这类周期任务:今天那份(剩余 < 周期)该催;
    明天那份(剩余 > 周期)今晚不该弹——等今天那份 4 点 closed、它顺延成当前份再催。
    一次性 end(无 recurrence_interval)不过滤,返回 False。
    """
    if task["drive"] != "end":
        return False
    interval = task.get("recurrence_interval")
    if not interval or interval <= 0:
        return False                       # 一次性 end,不按周期过滤
    now = now if now is not None else now_ts()
    deadline = task.get("deadline")
    if deadline is None:
        return False
    return (int(deadline) - now) > int(interval)


def _cooling_down(task, last_at, now=None):
    """任务是否在冷却(不该催)。snooze_until 优先;否则按 间隔×1/4。

    - snooze_until 非空且 now < snooze_until → 推迟未到点,冷却。
    - 否则:距上次推送不足「间隔×1/4」→ 冷却。无间隔字段兜底 COOLDOWN_FALLBACK。
    """
    now = now if now is not None else now_ts()
    snooze_until = task.get("snooze_until")
    if snooze_until and now < int(snooze_until):
        return True
    if not last_at:
        return False
    interval = _task_interval(task) or settings.get("cooldown_fallback")
    cooldown = max(int(interval * settings.get("cooldown_ratio")), 60)   # 至少 60s,避免高频狂弹
    return (now - int(last_at)) < cooldown


def _stage(task, nag_count):
    """根据任务与已推次数定档位。end 临近截止升级为 crisis(过期任务已被关闭,不在此列)。"""
    if task["drive"] == "end":
        if engine.end_importance(task["deadline"]) >= settings.get("crisis_importance"):
            return "crisis"
        if nag_count >= settings.get("escalate_nags"):
            return "escalating"
    else:
        if nag_count >= settings.get("escalate_nags") * 2:
            return "escalating"
    return "gentle"


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


def tick_push():
    """主入口:挑最多 max_concurrent 个最该催的(end 优先)→ 弹小卡并记录。"""
    conn = db.connect()
    db.init_db()
    actions.close_overdue(conn)            # 超时即关闭:过期 end 任务先落 closed
    ends, starts = engine.today_lists(conn)
    now = _now()
    limit = settings.get("max_concurrent")

    picked = []
    for task in ends + starts:             # end 优先,再 start(均已排序)
        if len(picked) >= limit:
            break
        if _is_future_period(task, now):   # 明天/后天的周期任务,今晚不催
            continue
        nag_count, last_at = db.push_stats(conn, task["id"])
        if _cooling_down(task, last_at, now):
            continue
        picked.append((task, _stage(task, nag_count)))
    for task, stage in picked:
        db.log_push(conn, task["id"], now, stage)
    conn.close()

    for task, stage in picked:
        on_done, on_snooze, on_ai = _make_callbacks(task["id"])
        show_task_card(task, stage, on_done, on_snooze, on_ai)
        print(f"[{to_str(now)}] 弹小卡: [{stage}] {task['title']}")
    return len(picked)
