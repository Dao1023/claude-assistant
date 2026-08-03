"""推送生命周期:按重要性挑任务,三档催促 + 节流 + 冷却,触发通知浮窗 + 写 push_log。

属于 io 层。按钮交互(完成/稍后/找AI)在前端 /notify 页,走 server 的 REST API;
本模块只负责「挑任务 → 写 push_log → 叫浮窗出来」。
过滤/定档逻辑走 core/funnel 管线(与规则页 /api/funnel 统计共用同一份,保证一致);
数值阈值读 core/settings,可在规则页配置。
"""
from ..core import actions, db, funnel, settings
from ..core.timeutil import now_ts, to_str
from . import events, notify_window


def _now():
    """写 push_log 用的当前 Unix 秒级时间戳。"""
    return now_ts()


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
    """主入口:挑本轮最该催的(end 优先)→ 写 push_log + 触发通知浮窗。

    不再每任务弹一张卡:浮窗是单例滚动列表(见 io/notify_window),
    挑到了就 show() 一次,前端 /notify 页自己拉全部待办渲染。
    按钮(完成/稍后/找AI)逻辑在前端,走 server 的 REST API,不在此。
    """
    conn = db.connect()
    db.init_db()
    actions.close_overdue(conn)            # 超时即关闭:过期 end 任务先落 closed
    now = _now()
    picked, _blocked = pick(conn, now)
    for task, stage, _nag in picked:
        db.log_push(conn, task["id"], now, stage)
    conn.close()

    if picked:
        notify_window.show()
        # 推给浮窗:通知层把「这次该催谁」作为事件快照推给订阅者,弹窗被动接收、不查询
        events.publish("notify", tasks=[
            {"id": t["id"], "title": t["title"], "stage": stage}
            for t, stage, _n in picked
        ])
        for _t, stage, _n in picked:
            print(f"[{to_str(now)}] 触发浮窗: [{stage}] {_t['title']}")
    return len(picked)
