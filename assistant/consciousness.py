"""意识层 · DSH 适配器:daemon 唤醒大脑的桥。

已验证的唤醒原语(2026-10 实测,DSH desktop CLI):
    dsh headless "任务文本"                  一次性唤醒,答案进 stdout(实测 ~3s)
    dsh headless --json ...                 NDJSON 事件流,含 sessionId
    dsh headless --session-id <id> "继续"   续接既有会话 = 大脑的连续记忆

设计纪律(见 docs/architecture.excalidraw):
- daemon 不认识任何 harness——本模块是意识层的 DSH 适配器;
  未来换/加 harness 时另写适配器,计时器与数据后端不动。
- 大脑会话 id 持久化在 data/brain_session.txt,跨唤醒续接;
  会话损坏/丢失时自动开新会话(大脑失忆,档案仍在)。

用法:
    from assistant.consciousness import wake
    answer, session_id = wake("到期提醒:xxx", timeout=120)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from .config import DATA

# dsh CLI 入口。默认指向桌面版安装位置,可用环境变量 DSH_CMD 覆盖
# (换 harness = 换这个命令 + 适配器,其余不动)。
DEFAULT_DSH_CMD = (
    r"C:\Users\Dao\AppData\Local\Programs\DeepSeek Harness"
    r"\resources\runtime\cli\bin\dsh.cmd"
)
SESSION_FILE = DATA / "brain_session.txt"


def _dsh_cmd() -> str:
    return os.environ.get("DSH_CMD", DEFAULT_DSH_CMD)


def load_session_id() -> Optional[str]:
    """读持久化的大脑会话 id;没有则 None(下次唤醒开新会话)。"""
    try:
        sid = SESSION_FILE.read_text(encoding="utf-8").strip()
        return sid or None
    except OSError:
        return None


def _save_session_id(sid: str) -> None:
    SESSION_FILE.write_text(sid.strip() + "\n", encoding="utf-8")


def _extract_session_id(ndjson_text: str) -> Optional[str]:
    """从 --json 的事件流里抠 sessionId(逐行找,容错行内顺序)。"""
    for line in ndjson_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        sid = obj.get("sessionId") or obj.get("session_id")
        if sid:
            return str(sid)
    return None


def _run(args: list[str], timeout: float) -> str:
    proc = subprocess.run(          # noqa: S603 列表参数,无 shell 拼接
        [_dsh_cmd(), "headless", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"dsh headless 失败(exit={proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    return proc.stdout.strip()


def wake(message: str, *, timeout: float = 120.0,
         session_id: Optional[str] = None) -> tuple[str, Optional[str]]:
    """唤醒大脑,返回 (回答文本, 会话id)。

    - 有持久化会话则续接(记忆连续),失败自动降级为新会话;
    - message 建议自带上下文(计时器到点事件/待办快照),大脑不记得没说过的。
    """
    sid = session_id or load_session_id()
    if sid:
        try:
            answer = _run(["--session-id", sid, message], timeout)
            return answer, sid
        except (RuntimeError, subprocess.TimeoutExpired):
            pass                    # 会话失效 → 开新的(大脑失忆,档案还在)

    # 新会话:用 --json 拿 sessionId
    out = _run(["--json", message], timeout)
    new_sid = _extract_session_id(out)
    if new_sid:
        _save_session_id(new_sid)
    # --json 模式下 stdout 是事件流,答案在 final 事件里;尽力抽最终文本
    answer = _extract_final_text(out) or out
    return answer, new_sid


def _extract_final_text(ndjson_text: str) -> Optional[str]:
    """从事件流里找最后一条消息文本(agent 的最终回答)。"""
    last: Optional[str] = None
    for line in ndjson_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        text = (obj.get("message") or obj.get("text")
                if isinstance(obj.get("message") or obj.get("text"), str) else None)
        if text:
            last = text
    return last


def reset_session() -> None:
    """让大脑失忆(新会话)。手动兜底用。"""
    SESSION_FILE.unlink(missing_ok=True)
