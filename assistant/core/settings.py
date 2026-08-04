"""通知规则设置:单一读写口。

数值型阈值存 SQLite settings 表,本模块提供 get/set/all,带进程内缓存。
规则页展示值 = 推送代码运行值,同源(都走本模块),不会不一致。
SETTINGS 是唯一事实来源:渲染、校验、默认、测试都从这里取。
"""
from . import db

# (key, default, type, unit, label, desc, min, max)
SETTINGS = [
    ("cooldown_ratio", 0.25, "float", "", "冷却系数",
     "冷却时长 = 任务间隔 × 此系数。越大催得越稀。", 0.05, 1.0),
    ("cooldown_fallback", 3600, "int", "秒", "兜底冷却",
     "任务无间隔字段时的冷却时长。", 60, 86400),
    ("escalate_nags", 3, "int", "次", "升级档次数",
     "end 被推这么多次后升「催办」;start 为其 2 倍。", 1, 20),
    ("crisis_importance", 1.0, "float", "", "危机重要性阈值",
     "end 重要性到此值(约剩 9 小时)无视次数直接「紧急」。", 0.0, 5.0),
    ("poll_interval", 30, "int", "秒", "轮询间隔",
     "调度循环每隔多久检查一次该不该催。", 5, 600),
    ("max_concurrent", 1, "int", "张", "一次最多弹卡",
     "同一轮最多弹出几张催办小卡。", 1, 5),
    ("dnd_night_end", 8, "int", "点", "夜间免打扰到",
     "每天 0:00 到这个点之前不弹卡(夜猫子默认,无需设开始)。", 0, 23),
]

_BY_KEY = {s[0]: s for s in SETTINGS}
_cache = None          # {key: 已转类型的值};None=未加载


def _coerce(key, raw):
    typ = _BY_KEY[key][2]
    return float(raw) if typ == "float" else int(float(raw))


def _load():
    """从库读全部已存值并合并默认值,填充缓存。库不可用时全用默认。"""
    global _cache
    stored = {}
    try:
        conn = db.connect()
        try:
            stored = db.all_settings(conn)
        finally:
            conn.close()
    except Exception:
        stored = {}
    _cache = {key: _coerce(key, stored[key]) if key in stored else s[1]
              for key, s in ((s[0], s) for s in SETTINGS)}


def get(key):
    """读某规则当前值(库里有用库存,没有用默认)。"""
    if key not in _BY_KEY:
        raise KeyError(f"未知设置项: {key}")
    if _cache is None:
        _load()
    return _cache[key]


def set(key, value):
    """校验后写库并更新缓存。越界 ValueError,未知 key KeyError。"""
    if key not in _BY_KEY:
        raise KeyError(f"未知设置项: {key}")
    v = _coerce(key, value)
    lo, hi = _BY_KEY[key][6], _BY_KEY[key][7]
    if not (lo <= v <= hi):
        raise ValueError(f"{key} 需在 [{lo}, {hi}] 之间,收到 {v}")
    conn = db.connect()
    try:
        db.set_setting(conn, key, v)
    finally:
        conn.close()
    if _cache is not None:
        _cache[key] = v


def all():
    """全部可编辑项 + 元信息,供规则页渲染。有序。"""
    return [{"key": k, "value": get(k), "type": s[2], "unit": s[3],
             "label": s[4], "desc": s[5], "min": s[6], "max": s[7]}
            for s in SETTINGS for k in (s[0],)]


# ---- 临时免打扰状态(dnd_until)----
# 这是「运行时状态」不是「规则」,故不进 SETTINGS(不在规则页渲染成配置行),
# 直接走 db 键值表。有明确到期时刻,过期自动失效。

def get_dnd_until():
    """临时免打扰的到期时间戳(Unix 秒);未设置 → None。"""
    try:
        conn = db.connect()
        try:
            raw = db.get_setting(conn, "dnd_until")
        finally:
            conn.close()
    except Exception:
        return None
    return int(raw) if raw else None


def set_dnd_until(until):
    """设临时免打扰到期时刻(Unix 秒);传 None 清除(立即恢复)。"""
    conn = db.connect()
    try:
        if until is None:
            db.set_setting(conn, "dnd_until", "")
        else:
            db.set_setting(conn, "dnd_until", int(until))
    finally:
        conn.close()


# ---- 文本型配置(LLM 后端等字符串)----
# 与上面的数值 SETTINGS 分开:字符串不能 _coerce 成 int/float,也无 min/max 校验。
# 走同一个 settings 表(键值),但独立的 get/set 通道,不在规则页数值区渲染。
# LLM 配置虽是秘密(key),但 settings 表与 data/key.md 同级(都在 .gitignore 的 data/),
# 安全性等价;且能被规则页编辑,比手改文件顺手。

TEXT_KEYS = ("llm_base_url", "llm_api_key", "llm_model")


def get_text(key, default=""):
    """读文本配置(如 llm_base_url);未设置 → default。未知 key KeyError。"""
    if key not in TEXT_KEYS:
        raise KeyError(f"未知文本设置项: {key}")
    try:
        conn = db.connect()
        try:
            raw = db.get_setting(conn, key)
        finally:
            conn.close()
    except Exception:
        return default
    return raw if raw not in (None, "") else default


def set_text(key, value):
    """写文本配置。传空串 = 清除(回退默认)。未知 key KeyError。"""
    if key not in TEXT_KEYS:
        raise KeyError(f"未知文本设置项: {key}")
    conn = db.connect()
    try:
        db.set_setting(conn, key, value if value else "")
    finally:
        conn.close()
