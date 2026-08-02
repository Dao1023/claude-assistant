"""通知过滤漏斗:一条纯函数管线,决定每个任务该不该被催。

为什么抽出来:漏斗逻辑既要给「实际推送」(pusher.tick_push)挑任务,
又要给「规则页」(/api/funnel)统计每层筛掉了哪些任务。两处共用同一条管线,
保证页面上看到的 = 真实推送会发生,不会两套逻辑对不上。

每层是一个纯函数:(task, ctx) -> 被挡原因 str 或 None(通过)。
任务按管线顺序往下流,算在被挡的第一层(数字不重复、不遗漏)。
未来加规则 = 往 FUNNEL 里插一个函数,推送与统计自动同时生效。

属于 core 层:不碰弹窗/HTTP,只算。ctx 由调用方备好(now + 每任务 push 统计)。
"""
from . import engine, settings
from .timeutil import now_ts, to_str


def fmt_duration(seconds):
    """秒 → 人话时长。取最大两个单位,如 '1 小时 20 分' / '2 天 3 小时' / '45 分'。"""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    parts = []
    for unit, size in (("天", 86400), ("小时", 3600), ("分", 60)):
        if seconds >= size:
            parts.append(f"{seconds // size} {unit}")
            seconds %= size
        if len(parts) == 2:
            break
    return " ".join(parts)

# 每层元信息:供规则页渲染(人话说明 + 该层挂的配置项 key)。
# 顺序即漏斗顺序。
LAYERS = [
    {"id": "dnd", "label": "免打扰",
     "desc": "总闸:夜间(0 点到设定点)或你手动开了免打扰,整条线冻结,一张都不弹。",
     "setting_keys": ["dnd_night_end"]},
    {"id": "future_period", "label": "未来周期",
     "desc": "周期任务是「明天/后天那份」(剩余超过一个周期),今晚不催,等轮到它。",
     "setting_keys": []},
    {"id": "snooze", "label": "推迟中",
     "desc": "你点了「稍后」,还没到约定时间,这期间不催。",
     "setting_keys": []},
    {"id": "cooldown", "label": "冷却中",
     "desc": "刚催过没多久,给你留喘息。冷却时长 = 任务间隔 × 冷却系数。",
     "setting_keys": ["cooldown_ratio", "cooldown_fallback"]},
    {"id": "limit", "label": "限量",
     "desc": "过了上面几关、本轮该催的任务,一次最多弹出这么多张,其余排队下轮。",
     "setting_keys": ["max_concurrent"]},
    {"id": "stage", "label": "定档位",
     "desc": "决定这张卡是「提醒 / 催办 / 紧急」。被推次数够多升级,快到截止直接紧急。",
     "setting_keys": ["escalate_nags", "crisis_importance"]},
]


def _task_interval(task):
    """任务的间隔(秒):start 用 expected_duration,end 用 recurrence_interval。无则 None。"""
    if task["drive"] == "start":
        return task.get("expected_duration")
    return task.get("recurrence_interval")


def dnd_active(now):
    """免打扰总闸:命中返回原因 str,畅通返回 None。

    两个来源,任一命中即冻结整条流水线(不是单任务过滤,故在 pick() 顶部调,
    不进单任务管线 run_pipe):
    - 夜间:每天 0 点到 dnd_night_end 点之间(夜猫子默认,不跨天)。
    - 临时:手动开了免打扰,now < dnd_until(到期自动恢复)。
    """
    from datetime import datetime
    until = settings.get_dnd_until()
    if until and now < until:
        return f"手动免打扰到 {to_str(until)},还剩 {fmt_duration(until - now)}"
    night_end = settings.get("dnd_night_end")
    hour = datetime.fromtimestamp(int(now)).hour
    if hour < night_end:
        return f"夜间免打扰(0~{night_end} 点),现在 {hour} 点"
    return None


def check_future_period(task, ctx):
    """周期 end 是明天/后天那份(剩余 > 一个周期)→ 被挡。"""
    if task["drive"] != "end":
        return None
    interval = task.get("recurrence_interval")
    if not interval or interval <= 0:
        return None                       # 一次性 end,不按周期过滤
    deadline = task.get("deadline")
    if deadline is None:
        return None
    if (int(deadline) - ctx["now"]) > int(interval):
        left = int(deadline) - ctx["now"]
        return f"截止 {to_str(deadline)},还有 {fmt_duration(left)},明天/后天那份今晚不催"
    return None


def check_snooze(task, ctx):
    """推迟(snooze)未到点 → 被挡。"""
    snooze_until = task.get("snooze_until")
    if snooze_until and ctx["now"] < int(snooze_until):
        left = int(snooze_until) - ctx["now"]
        return f"推迟到 {to_str(snooze_until)},还剩 {fmt_duration(left)}"
    return None


def check_cooldown(task, ctx):
    """距上次推送不足「间隔×冷却系数」→ 被挡。无间隔字段用兜底冷却。"""
    last_at = ctx.get("last_at")
    if not last_at:
        return None
    interval = _task_interval(task) or settings.get("cooldown_fallback")
    ratio = settings.get("cooldown_ratio")
    cooldown = max(int(int(interval) * ratio), 60)   # 至少 60s
    elapsed = ctx["now"] - int(last_at)
    if elapsed < cooldown:
        return (f"已过 {fmt_duration(elapsed)} / 冷却 {fmt_duration(cooldown)}"
                f" = 间隔 {fmt_duration(interval)} × 冷却系数 {ratio}")
    return None


def check_stage(task, ctx):
    """定档位层不过滤,恒通过(档位由 stage() 单独算)。存在仅为向用户展示这一层。"""
    return None


# 过滤管线:按序执行,返回第一个被挡的层 id 与原因。全通过返回 (None, None)。
PIPE = [
    ("future_period", check_future_period),
    ("snooze", check_snooze),
    ("cooldown", check_cooldown),
]


def run_pipe(task, ctx):
    """让一个任务流过过滤管线。返回 (blocked_layer_id, reason);全通过 (None, None)。

    注意:limit(限量)与 stage(定档位)不在此管线——limit 是挑出后按数量截断,
    stage 是给通过者定档,二者作用于「已通过过滤的任务集合」,不是单任务过滤。
    """
    for layer_id, fn in PIPE:
        reason = fn(task, ctx)
        if reason is not None:
            return layer_id, reason
    return None, None


def stage(task, nag_count):
    """给通过过滤的任务定档位。end 临近截止无视次数直接 crisis。"""
    if task["drive"] == "end":
        if engine.end_importance(task["deadline"]) >= settings.get("crisis_importance"):
            return "crisis"
        if nag_count >= settings.get("escalate_nags"):
            return "escalating"
    else:
        if nag_count >= settings.get("escalate_nags") * 2:
            return "escalating"
    return "gentle"


def make_ctx(now=None, last_at=None):
    """构造过滤上下文。now 缺省取当前;last_at 为该任务上次推送时间(无则 None)。"""
    return {"now": now if now is not None else now_ts(), "last_at": last_at}
