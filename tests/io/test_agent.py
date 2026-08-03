"""测试:AI 旁观 Agent(io/agent)——旁观→判断→开口→记日志 全链路,不碰真模型。

用 MockBackend 替代真 DeepSeek;事件手工构造喂 queue。断言:
- 关键事件(snooze/done)触发判断,模型说话则 publish ai_message + 记日志;
- 模型沉默(SILENT)则不发事件;
- 工作记忆持久化到 JSON;
- 调用过程写 JSONL 日志;
- 自己发的 ai_message 不自激。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant.io import agent as agent_mod
from assistant.io import events
from assistant.io.agent import Agent
from assistant.io.llm import MockBackend


@pytest.fixture()
def published(monkeypatch):
    """截获 events.publish 调用,返回 [(type, payload), ...]。"""
    calls = []

    def fake_publish(event_type, **payload):
        calls.append((event_type, payload))
    monkeypatch.setattr(agent_mod.events, "publish", fake_publish)
    return calls


@pytest.fixture()
def agt(tmp_path):
    """一个用临时文件、MockBackend 的 Agent(不起线程,直接调 _handle)。"""
    backend = MockBackend()
    a = Agent(backend=backend,
              memory_file=tmp_path / "mem.json",
              log_file=tmp_path / "log.jsonl")
    return a


def _snooze(title="写报告", note=None, ts=1000):
    return {"type": "snooze", "ts": ts, "task_id": "t1",
            "title": title, "note": note, "until": 2000}


def _done(title="写报告", note=None, ts=1001):
    return {"type": "done", "ts": ts, "task_id": "t1",
            "title": title, "note": note}


# ---------- 开口 ----------

def test_snooze_triggers_judge_and_speaks(agt, published):
    agt._handle(_snooze(note="先去开个会"))
    # Mock 默认开口 → 应发 ai_message
    msgs = [p for t, p in published if t == "ai_message"]
    assert msgs, "应发布 ai_message"
    assert msgs[0]["kind"] == "nudge"
    assert msgs[0]["text"]


def test_silent_model_does_not_publish(tmp_path, published):
    backend = MockBackend(reply="SILENT")
    a = Agent(backend=backend,
              memory_file=tmp_path / "mem.json",
              log_file=tmp_path / "log.jsonl")
    a._handle(_snooze())
    assert published == []                     # 沉默 → 什么事件都不发


def test_backend_none_never_judges(tmp_path, published):
    a = Agent(backend=None,
              memory_file=tmp_path / "mem.json",
              log_file=tmp_path / "log.jsonl")
    a._handle(_snooze())
    a._handle(_done())
    assert published == []                     # 无后端:只旁观,不开口
    # 但记忆照攒
    assert len(a._memory) == 2


# ---------- 记忆 ----------

def test_memory_accumulates_and_persists(agt):
    agt._handle(_snooze(ts=1))
    agt._handle(_done(ts=2))
    assert len(agt._memory) == 2
    # JSON 已落盘
    saved = json.loads(agt._memory_file.read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[0]["type"] == "snooze"


def test_memory_capped(agt):
    agt._memory = [{"type": "dnd", "ts": i} for i in range(agent_mod.MAX_MEMORY_EVENTS)]
    agt._handle(_snooze())
    assert len(agt._memory) == agent_mod.MAX_MEMORY_EVENTS


def test_notify_does_not_trigger_judge(agt, published):
    """notify 只攒记忆,不单独触发判断(省钱,单次推送说明不了什么)。"""
    agt._handle({"type": "notify", "ts": 1,
                 "tasks": [{"id": "t1", "title": "写报告", "stage": "gentle"}]})
    assert published == []
    assert len(agt._memory) == 1


# ---------- 自激防护 ----------

def test_own_ai_message_ignored(agt, published):
    """Agent 自己发的 ai_message 不该再触发自己判断(自激)。"""
    agt._handle({"type": "ai_message", "ts": 1, "text": "你在偷懒吗", "kind": "nudge"})
    assert len(agt._memory) == 0               # 不进记忆
    assert published == []


# ---------- 调用日志 ----------

def test_log_written(agt):
    agt._handle(_snooze(note="在忙"))
    entries = agent_mod.read_log(limit=10, log_file=agt._log_file)
    kinds = [e["kind"] for e in entries]
    assert "observe" in kinds                  # 观察(喂模型前)
    assert "speak" in kinds                    # 开口


def test_read_log_empty(tmp_path):
    assert agent_mod.read_log(log_file=tmp_path / "none.jsonl") == []


# ---------- 事件格式化(给模型看的上下文) ----------

def test_fmt_event_includes_note(agt):
    s = agt._fmt_event(_snooze(title="写报告", note="先开会"))
    assert "推迟" in s and "先开会" in s


# ---------- 订阅机制(events 层) ----------

def test_local_subscribe_receives_event():
    received = []
    events.subscribe_local(received.append)
    try:
        events.publish("snooze", task_id="t1", note="x")
    finally:
        events.unsubscribe_local(received.append)
    assert len(received) == 1
    assert received[0]["type"] == "snooze"
    assert received[0]["ts"]                   # publish 打了时间戳
    assert received[0]["note"] == "x"


def test_local_subscriber_error_does_not_break_publish():
    def bad(ev):
        raise RuntimeError("boom")
    good = []
    events.subscribe_local(bad)
    events.subscribe_local(good.append)
    try:
        events.publish("dnd", until=None)      # 不该抛
    finally:
        events.unsubscribe_local(bad)
        events.unsubscribe_local(good.append)
    assert len(good) == 1                      # 坏订阅者不影响好的
