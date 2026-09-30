"""计时器:daemon 的唤醒节拍器(V4.1)。

三种计时器(见 docs/architecture.excalidraw):
- 本体计时器:不可关闭,每 10min 让大脑做一次基本回顾(待机档用)
- 自定义计时器:大脑/用户设置的一次性/周期提醒
- 跳跃提醒 = 周期触发后由大脑重设 fire_at(下次隔多久它自己判断)

设计纪律:
- 本模块纯确定性,不 import 意识层/不调模型——它只决定「什么时候该叫」,
  叫醒之后说什么、做什么是大脑的事(命令行 --wake 才接 consciousness)。
- 冲突自解 = 到点的计时器合并成一个批次,一次唤醒处理(去抖)。
- 睡眠语义(见 docs/rhythm.md):awake=False 时计时器不唤醒,只把错过
  的提醒记入 missed,醒后第一批上下文补课。

持久化:data/timers.json(临时文件 + 原子替换)。

用法:
    from assistant.timers import TimerEngine
    eng = TimerEngine()
    eng.add("once", in_sec=3600, label="交材料", payload="材料今天 17:00 截止")
    batch = eng.due_batch(now)          # -> {"reason","message"} | None
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from pathlib import Path
from typing import Optional

from .config import DATA

TIMER_FILE = DATA / "timers.json"
REVIEW_EVERY = 600  # 本体计时器:10 分钟

VALID_KINDS = ("once", "interval")


def _now() -> int:
    return int(time.time())


class TimerEngine:
    """计时器引擎:持有 timers.json,推进节拍,产出唤醒批次。"""

    def __init__(self, path: Optional[Path] = None, review_every: int = REVIEW_EVERY):
        self._path = Path(path) if path else TIMER_FILE
        self._review_every = review_every
        self._state = self._load()

    # ---------- 持久化 ----------

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"meta": {"last_review": 0}, "timers": [], "missed": []}

    def _save(self) -> None:
        tmp = self._path.with_suffix(f".{random.randrange(1 << 30):x}.tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self._path)

    # ---------- 设置/查询(大脑与用户共用的命令面) ----------

    def add(self, kind: str, *, at: Optional[int] = None, in_sec: Optional[int] = None,
            every: Optional[int] = None, label: str = "", payload: str = "",
            by: str = "user", now: Optional[int] = None) -> str:
        """加一个计时器。once 用 at/in_sec;interval 用 every(可选首 fire at/in_sec)。

        now 可注入(测试/回放用),缺省取当前墙钟。
        """
        if kind not in VALID_KINDS:
            raise ValueError(f"kind 必须是 {VALID_KINDS},收到 {kind!r}")
        now = now if now is not None else _now()
        if kind == "interval":
            if not every or every <= 0:
                raise ValueError("interval 计时器必须给 every>0(秒)")
            fire_at = at if at is not None else now + (in_sec if in_sec is not None else every)
        else:
            if at is None and in_sec is None:
                raise ValueError("once 计时器必须给 at 或 in_sec")
            fire_at = at if at is not None else now + in_sec
        tid = f"t-{uuid.uuid4().hex[:10]}"
        self._state["timers"].append({
            "id": tid, "kind": kind, "label": label, "payload": payload,
            "fire_at": int(fire_at), "interval": int(every) if every else None,
            "by": by,
        })
        self._save()
        return tid

    def remove(self, tid: str) -> bool:
        before = len(self._state["timers"])
        self._state["timers"] = [t for t in self._state["timers"] if t["id"] != tid]
        hit = len(self._state["timers"]) < before
        if hit:
            self._save()
        return hit

    def reset(self, tid: str, *, at: Optional[int] = None, in_sec: Optional[int] = None,
              now: Optional[int] = None) -> bool:
        """跳跃提醒的大脑侧:触发后重设下次时间。"""
        now = now if now is not None else _now()
        for t in self._state["timers"]:
            if t["id"] == tid:
                t["fire_at"] = at if at is not None else now + (in_sec or 0)
                self._save()
                return True
        return False

    def list(self) -> list[dict]:
        return sorted(self._state["timers"], key=lambda t: t["fire_at"])

    @property
    def missed(self) -> list[dict]:
        return list(self._state["missed"])

    # ---------- 节拍推进 ----------

    def due_batch(self, now: Optional[int] = None, awake: bool = True) -> Optional[dict]:
        """推进节拍,返回一个唤醒批次;无事发生返回 None。

        优先级:错过的补课 > 到点的自定义计时器 > 本体回顾。
        awake=False 时:自定义计时器不唤醒只记账;本体回顾不触发。
        """
        now = now if now is not None else _now()

        # 1) 醒来第一件事:补课(睡眠期间错过的)
        if awake and self._state["missed"]:
            missed, self._state["missed"] = self._state["missed"], []
            self._save()
            return {
                "reason": "missed",
                "count": len(missed),
                "message": "你在睡眠期间错过了以下提醒,请检查是否需要补办:\n"
                           + "\n".join(
                               f"- [{m['label'] or '提醒'}] {m['payload']}"
                               f"(应触发于 {-(-(now - m['fired_at']) // 60)} 分钟前)"
                               for m in missed),
            }

        # 2) 到点的自定义计时器(合并成一批 = 冲突自解)
        due = [t for t in self._state["timers"] if t["fire_at"] <= now]
        if due:
            due_ids = {t["id"] for t in due}
            kept, missed_new = [], []
            for t in self._state["timers"]:
                if t["id"] not in due_ids:
                    kept.append(t)
                    continue
                if t["kind"] == "interval":
                    # 周期:顺延(跳过所有已错过的整周期,不补发历史)
                    while t["fire_at"] <= now:
                        t["fire_at"] += t["interval"]
                    kept.append(t)
                # once:触发即出列
            self._state["timers"] = kept
            if awake:
                self._save()
                return {
                    "reason": "timers",
                    "count": len(due),
                    "message": "以下计时器到点:\n" + "\n".join(
                        f"- [{t['label'] or t['id']}] {t['payload']}" for t in due),
                }
            # 睡眠:不唤醒,保存唤醒记录(rhythm.md 睡眠语义)
            for t in due:
                missed_new.append({"label": t["label"], "payload": t["payload"],
                                   "fired_at": t["fire_at"]})
            self._state["missed"].extend(missed_new)
            self._save()
            return None

        # 3) 本体计时器:待机档的定期基本回顾
        if awake and now - self._state["meta"].get("last_review", 0) >= self._review_every:
            self._state["meta"]["last_review"] = now
            self._save()
            return {
                "reason": "review",
                "count": 1,
                "message": "本体计时器定期回顾:请简短检查当前是否有需要用户知道或处理的事,没有则只回「无事」。",
            }
        return None


def _cli() -> None:  # pragma: no cover - 手动入口
    import argparse
    p = argparse.ArgumentParser(description="计时器引擎(手动/调试入口)")
    p.add_argument("--loop", action="store_true", help="常驻循环,每 30s 推进一次")
    p.add_argument("--wake", action="store_true", help="到点时真的唤醒大脑(consciousness)")
    p.add_argument("--add-once", metavar="SEC", type=int, help="加一个 N 秒后的一次性提醒(测试)")
    p.add_argument("--add-payload", default="测试提醒", help="配合 --add-once 的载荷")
    args = p.parse_args()

    eng = TimerEngine()
    if args.add_once is not None:
        tid = eng.add("once", in_sec=args.add_once, label="测试",
                      payload=args.add_payload, by="user")
        print(f"已加: {tid} ({args.add_once}s 后)")
        return

    if not args.loop:
        batch = eng.due_batch()
        print(json.dumps(batch, ensure_ascii=False) if batch else "无事发生")
        return

    from . import consciousness  # 延迟 import:循环+--wake 才需要
    while True:
        batch = eng.due_batch()
        if batch:
            print(f"[{_now()}] {batch['reason']}: {batch['message'][:80]}...")
            if args.wake:
                answer, sid = consciousness.wake(batch["message"])
                print(f"大脑: {answer}  (session={sid})")
        time.sleep(30)


if __name__ == "__main__":  # pragma: no cover
    _cli()
