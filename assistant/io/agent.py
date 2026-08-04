"""AI 旁观 Agent(第四层):常驻旁观事件流,自主决定沉默还是开口。

四层定位:①事件 ②通知 ③弹窗 ④AI。本模块是第④层——只旁观前三层的事件,
绝不改前三层;想说话就 publish 一个 ai_message 事件回总线,浮窗被动渲染。

工作方式:
- subscribe_local 注册回调,事件进 queue(回调轻,只丢 queue);
- 自己的 daemon 线程消费 queue,把事件攒进「工作记忆」;
- 攒够一批(或关键事件)就调 LLM 判断「现在该不该开口」;
- 判断过程全程写 JSONL 调用日志(让前端「AI 看了啥」可见);
- 开口则 publish ai_message,并把这句话也记进对话。

记忆(见 docs/architecture.md「三层记忆」):
- 工作记忆:本次事件流,内存 list + JSON 持久化(重启可恢复),单文件反复读写,JSON 合适。
- 情景记忆:白捡的 push_log 留言,由 prompt 拼装时读取(本模块不重建)。
- 语义记忆(用户画像):留待 D 步,A~C 步先不压。

沉默优先:大多数判断结果是「不说话」。模型输出 SILENT 即沉默,否则输出即开口内容。
"""
import json
import queue
import threading

from ..config import DATA
from ..core import engine
from ..core.timeutil import now_ts, to_str
from . import events

MEMORY_FILE = DATA / "agent_memory.json"      # 工作记忆(单文件,反复读写)
LOG_FILE = DATA / "agent_log.jsonl"           # 调用过程日志(追加,一行一条)

# 工作记忆上限:超出就把最早的丢掉(D 步再换成滚动摘要压缩)
MAX_MEMORY_EVENTS = 60

# 系统提示词:走 API 的 system 字段(不进 messages),作前缀缓存的稳定前缀。
# 只放「身份 + 能力边界 + 语气」——主动判断的 SILENT 协议不在这里,
# 而在 _maybe_speak 的 user prompt 里(被回复的 reply 路不该背 SILENT 规则)。
_SYSTEM_PROMPT = """<身份>
你是「双驱动任务系统」的助手,常驻旁观用户的任务。
系统规则:start 驱动 = 一个任务越久没做越重要;end 驱动 = 离截止越近越急。
</身份>

<你能看到什么>
- 用户当前的任务清单(随对话附上):临期任务的标题和截止、长期任务的标题。
- 用户的任务行为记录:推送、完成、推迟、免打扰,推迟/完成可能带一句留言。
你能看到这些,就能聊任务、给建议。清单里没有的细节(具体进度、为啥卡)你看不到,
被问到就老实说不知道,别编。
</你能看到什么>

<怎么说话>
- 像朋友,简短,一两句点到为止,不说教、不长篇大论、不端着。
- 给建议要具体、落到实处,基于你看到的任务;别给空洞的「加油」「你可以的」。
- 用户在气头上或被催烦了,先接住情绪(「我懂,这事是挺磨人」),再说正事;
  绝不回「不用这样」「别激动」这种居高临下的话。
- 不知道就说不知道,做不到就说做不到,诚实比圆滑重要。
</怎么说话>"""

# 主动判断专属的输出协议(只用于 _maybe_speak,不进系统提示词,
# 免得被回复的 reply 路也背上 SILENT 规则而把协议字面量漏给用户)。
_JUDGE_INSTRUCTION = """<任务>
判断现在该不该主动开口提醒用户。绝大多数时候该沉默——只在出现明确异常时开口:
- 同一个任务短期内反复推迟(比如连着推了 2、3 次);
- 长时间只有推迟、没有任何完成;
- 留言总在找借口(每次都「太累了」「等会儿」却不见行动)。
没有这些信号就沉默,别为了说话而说话。
</任务>

<输出格式>
严格遵守,二选一,不要任何前后缀或解释:
- 不该开口 → 只回:SILENT
- 该开口   → 只回要问用户的那一句话
</输出格式>"""


class Agent:
    """旁观 Agent。backend 为 None 时退化:只攒记忆、不判断不开口(无 key 也能跑)。"""

    def __init__(self, backend=None, memory_file=MEMORY_FILE, log_file=LOG_FILE):
        self._backend = backend
        self._memory_file = memory_file
        self._log_file = log_file
        self._queue = queue.Queue()
        self._memory = self._load_memory()
        self._dialog = []                   # LLM 多轮上下文([{role,content}])
        self._thread = None
        self._started = False

    # ---- 订阅入口(在 publish 方线程被调,务必轻) ----

    def on_event(self, event: dict):
        """events.subscribe_local 的回调:只丢 queue,不处理。"""
        self._queue.put(event)

    # ---- 生命周期 ----

    def start(self):
        """注册订阅 + 起消费线程(幂等,daemon)。"""
        if self._started:
            return
        events.subscribe_local(self.on_event)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="ai-agent")
        self._thread.start()
        self._started = True

    def stop(self):
        events.unsubscribe_local(self.on_event)

    # ---- 主循环 ----

    def _run(self):
        while True:
            event = self._queue.get()
            try:
                self._handle(event)
            except Exception as e:
                # 单次事件处理失败不拖垮 Agent;记进日志便于诊断
                self._log("error", {"error": str(e), "event": event})

    def _handle(self, event: dict):
        # 忽略自己发出的 ai_message,免得自激(自己说的话又触发自己判断)
        if event.get("type") == "ai_message":
            return
        self._remember(event)
        # 只在「值得判断」的事件上调用模型:推迟/完成是关键信号;
        # notify 攒着,等够一批再判断(省钱,且单次推送说明不了什么)
        if event.get("type") in ("snooze", "done"):
            self._maybe_speak(trigger=event)

    # ---- 记忆 ----

    def _remember(self, event: dict):
        self._memory.append(event)
        if len(self._memory) > MAX_MEMORY_EVENTS:
            self._memory = self._memory[-MAX_MEMORY_EVENTS:]
        self._save_memory()

    def _load_memory(self):
        try:
            if self._memory_file.exists():
                return json.loads(self._memory_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save_memory(self):
        try:
            self._memory_file.write_text(
                json.dumps(self._memory, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    # ---- 判断与开口 ----

    def _maybe_speak(self, trigger: dict):
        """把近期事件喂给模型,问它该不该开口。全过程记日志。"""
        if self._backend is None:
            return
        prompt = self._build_prompt(trigger)
        self._log("observe", {"trigger": trigger,
                              "memory_size": len(self._memory),
                              "prompt": prompt})
        try:
            out = self._backend.judge(prompt, context=self._dialog,
                                      system=_SYSTEM_PROMPT)
        except Exception as e:
            self._log("llm_error", {"error": str(e)})
            return

        if out.strip().upper().startswith("SILENT") or not out.strip():
            self._log("silent", {"reason": "模型判断沉默"})
            return

        # 开口:维护对话上下文 + 发事件 + 记日志
        self._dialog.append({"role": "user", "content": prompt})
        self._dialog.append({"role": "assistant", "content": out})
        self._trim_dialog()
        self._log("speak", {"text": out})
        events.publish("ai_message", text=out, kind="nudge")

    def _trim_dialog(self):
        # 多轮上下文别无限长:保留最近 10 轮(D 步再做滚动摘要)
        if len(self._dialog) > 20:
            self._dialog = self._dialog[-20:]

    @staticmethod
    def _task_snapshot() -> str:
        """拉一份当前任务清单的人话快照,注入 prompt 让 AI「看到」任务。

        只读 engine.today_lists,不改前三层。失败(DB 异常等)返回空串,
        调用方降级为不带清单——快照是增强,不是硬依赖。
        """
        try:
            ends, starts = engine.today_lists()
        except Exception:
            return ""
        lines = []
        if ends:
            lines.append("临期/截止任务(越近越急):")
            for t in ends:
                ddl = t.get("deadline") or "无明确截止"
                lines.append(f"- {t['title']}(截止:{ddl})")
        if starts:
            lines.append("长期任务(越久没做越重要):")
            for t in starts:
                lines.append(f"- {t['title']}")
        if not lines:
            return "当前没有任何活跃任务。"
        return "\n".join(lines)

    def _build_prompt(self, trigger: dict) -> str:
        """拼判断 prompt。顺序贴前缀缓存:任务清单(较稳)在前,事件流(变动)在后,
        判断协议(_JUDGE_INSTRUCTION)压尾。"""
        lines = ["以下是用户当前的任务清单:", self._task_snapshot(), ""]
        lines.append("以下是用户最近的任务行为事件流(按时间):")
        for ev in self._memory[-20:]:
            lines.append("- " + self._fmt_event(ev))
        lines.append("")
        lines.append("最新事件:" + self._fmt_event(trigger))
        lines.append("")
        lines.append(_JUDGE_INSTRUCTION)
        return "\n".join(lines)

    @staticmethod
    def _fmt_event(ev: dict) -> str:
        t = to_str(ev.get("ts")) if ev.get("ts") else "?"
        kind = ev.get("type", "?")
        if kind == "notify":
            titles = "、".join(x.get("title", "?") for x in ev.get("tasks", []))
            return f"[{t}] 推送:{titles}"
        if kind == "snooze":
            note = f"(留言:{ev['note']})" if ev.get("note") else ""
            return f"[{t}] 推迟了任务{note}"
        if kind == "done":
            note = f"(留言:{ev['note']})" if ev.get("note") else ""
            return f"[{t}] 完成了任务{note}"
        if kind == "dnd":
            return f"[{t}] {'开了免打扰' if ev.get('until') else '关了免打扰'}"
        if kind == "user_reply":
            return f"[{t}] 用户回复:{ev.get('text', '')}"
        return f"[{t}] {kind}"

    # ---- 调用日志 ----

    def _log(self, kind: str, data: dict):
        """追加一条调用过程日志(JSONL)。供前端「AI 看了啥」展示。"""
        try:
            line = json.dumps({"ts": now_ts(), "kind": kind, **data},
                              ensure_ascii=False)
            with self._log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    # ---- 用户回复(浮窗左列回话) ----

    def reply(self, text: str):
        """用户在浮窗回了一句:记进事件流(进记忆)+ 让模型接话。

        用户主动开口,就不是「该不该说」的问题,必须接话——所以这条路
        不用 SILENT 协议;模型若仍习惯性回 SILENT,拦截改默认接话,绝不把
        这个字面量透给用户。
        """
        events.publish("user_reply", text=text)
        if self._backend is None:
            return
        prompt = (
            "以下是用户当前的任务清单(供你参考回答):\n"
            + self._task_snapshot()
            + f"\n\n用户对你说:「{text}」。"
            "他正在和你对话,请结合上面的任务清单直接回应(简短、像朋友,不要长篇说教)。"
            "若他问任务/求建议,就根据清单给具体、实在的回答。"
            "这是对话不是旁观判断,不要用 SILENT。"
        )
        self._log("user_reply", {"text": text})
        try:
            out = self._backend.judge(prompt, context=self._dialog,
                                      system=_SYSTEM_PROMPT)
        except Exception as e:
            self._log("llm_error", {"error": str(e)})
            return
        # 兜底:用户主动对话不该收到 SILENT;模型若仍回,换成顺滑的接话
        if out.strip().upper().startswith("SILENT") or not out.strip():
            out = "我在。你接着说,或者点名一个任务,咱具体聊。"
        self._dialog.append({"role": "user", "content": prompt})
        self._dialog.append({"role": "assistant", "content": out})
        self._trim_dialog()
        self._log("speak", {"text": out})
        events.publish("ai_message", text=out, kind="reply")


# ---- 全局单例(进程内一个 Agent) ----

_agent = None


def read_log(limit: int = 100, log_file=LOG_FILE) -> list:
    """读调用过程日志最后 limit 条(倒序,最新在前)。供 /api/ai/log。"""
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in reversed(lines[-limit:]):
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries
    except Exception:
        return []


def read_history(limit: int = 50, log_file=LOG_FILE) -> list:
    """从日志滤出对话时间线(正序,供浮窗重载后回填)。

    时间线 = 一条流,AI 每次看了啥、想了啥、说没说,全摆出来不藏:
    - user_reply → {role:user};speak → {role:ai}(主动 nudge 和接话都算);
    - observe  → {role:system, kind:observe}:一次判断,带完整 prompt
                 (AI 当时看到的任务清单+事件流原文)和触发事件,前端全展开;
    - silent   → {role:system, kind:silent}:看了但选择沉默(也是一次判断);
    - llm_error→ {role:system, kind:llm_error}:调模型失败,前端淡红行。
    返回 [{role,text,ts,kind?,prompt?,trigger?}],正序。
    """
    if not log_file.exists():
        return []
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            kind = e.get("kind")
            if kind == "user_reply":
                out.append({"role": "user", "text": e.get("text", ""),
                            "ts": e.get("ts")})
            elif kind == "speak":
                out.append({"role": "ai", "text": e.get("text", ""),
                            "ts": e.get("ts")})
            elif kind == "observe":
                # 一次旁观判断:AI 看了啥(prompt 原文)+ 被什么触发,全展开
                out.append({"role": "system", "kind": "observe",
                            "text": "",
                            "prompt": e.get("prompt", ""),
                            "trigger": e.get("trigger"),
                            "ts": e.get("ts")})
            elif kind == "silent":
                out.append({"role": "system", "kind": "silent",
                            "text": e.get("reason", "模型判断沉默"),
                            "ts": e.get("ts")})
            elif kind == "llm_error":
                out.append({"role": "system", "kind": "llm_error",
                            "text": e.get("error", "模型调用失败"),
                            "ts": e.get("ts")})
        return out[-limit:]                  # 只留最近 limit 条,正序
    except Exception:
        return []


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent


def start_agent(backend=None) -> Agent:
    """装配并启动全局 Agent(幂等)。backend 缺省按 key 配置自动选。"""
    global _agent
    if _agent is None:
        if backend is None:
            backend = _auto_backend()
        _agent = Agent(backend=backend)
    _agent.start()
    return _agent


def _auto_backend():
    """有 key 用 DeepSeek,没有则 None(Agent 退化只旁观不开口)。"""
    from . import llm
    cfg = llm.load_key_config()
    if cfg:
        try:
            return llm.DeepSeekBackend(cfg)
        except Exception:
            return None
    return None
