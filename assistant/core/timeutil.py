"""时间转换:系统内部一律 Unix 秒级整数,边界(HTTP/前端)仍传字符串。

core 层工具,不依赖其他模块。约定:
- 内部存储/计算:int 时间戳(本地时区)。
- 边界字符串:'YYYY-MM-DD'(按当天 00:00)或 'YYYY-MM-DD HH:MM'。
"""
import time
from datetime import datetime

SECONDS_PER_DAY = 86400


def now_ts() -> int:
    """当前 Unix 秒级时间戳。"""
    return int(time.time())


def to_ts(s) -> int | None:
    """边界字符串 → Unix int。支持 'YYYY-MM-DD' / 'YYYY-MM-DD HH:MM'(:SS 也兼容)。

    None / 空串 → None。已是 int 则原样返回(幂等,方便边界直接透传)。
    """
    if s is None or s == "":
        return None
    if isinstance(s, int):
        return s
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    raise ValueError(f"无法解析的时间字符串: {s!r}(期望 'YYYY-MM-DD' 或 'YYYY-MM-DD HH:MM')")


def to_str(ts) -> str | None:
    """Unix int → 'YYYY-MM-DD HH:MM'(DDL 显示 / date-picker 回填)。None → None。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")


def to_date_str(ts) -> str | None:
    """Unix int → 'YYYY-MM-DD'(START 锚点显示 / date-picker 回填)。None → None。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
