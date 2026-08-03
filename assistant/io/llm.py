"""LLM 后端抽象:AI 层的「大脑」接口 + 各实现。

为什么抽象成 LLMBackend:用户要可插拔换模型——DeepSeek 便宜云(主力)、
本地 LM Studio(备用)、Mock(测试)。Agent 只面向 judge() 接口,不关心背后是哪家。

DeepSeek 接法:httpx 直连 Anthropic 兼容端点 /v1/messages(不引 SDK,减依赖)。
配置从 data/key.md 读(该文件在 .gitignore,key 不落代码/日志/git)。

安全:key 只在内存里读用,绝不打印、不进异常信息、不进 JSONL 调用日志。
"""
import json
from typing import Optional, Protocol

import httpx

from ..config import DATA

KEY_FILE = DATA / "key.md"


class LLMBackend(Protocol):
    """AI 后端协议:judge 输入 prompt,输出模型的文本回应。"""

    def judge(self, prompt: str, context: Optional[list] = None) -> str:
        """让模型判断。context 为可选的多轮对话历史([{role, content}])。"""
        ...


def load_key_config() -> Optional[dict]:
    """从 data/key.md 读 LLM 配置(DeepSeek 的 Anthropic 端点 + key + 模型)。

    文件是用户手写的一组 "KEY": "value" 行。解析容错:抽引号包住的键值对。
    读不到/没有 token 则返回 None(表示未配置,Agent 退化为不调用)。
    """
    if not KEY_FILE.exists():
        return None
    try:
        text = KEY_FILE.read_text(encoding="utf-8")
        cfg = {}
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k = k.strip().strip('"')
            v = v.strip().strip('"')
            if k:
                cfg[k] = v
        if not cfg.get("ANTHROPIC_AUTH_TOKEN"):
            return None
        return cfg
    except Exception:
        return None


class DeepSeekBackend:
    """DeepSeek 便宜云(Anthropic 兼容端点)。

    base_url 形如 https://api.deepseek.com/anthropic,拼 /v1/messages。
    auth 用 x-api-key 头(Anthropic 协议)。默认模型 deepseek-v4-pro(判断),
    想更省可配 flash。
    """

    def __init__(self, cfg: Optional[dict] = None, timeout: float = 60.0):
        cfg = cfg or load_key_config()
        if not cfg:
            raise RuntimeError("未配置 LLM key(data/key.md)")
        self._base = cfg["ANTHROPIC_BASE_URL"].rstrip("/")
        self._key = cfg["ANTHROPIC_AUTH_TOKEN"]
        self._model = cfg.get("ANTHROPIC_MODEL", "deepseek-v4-pro")
        self._timeout = timeout

    def judge(self, prompt: str, context: Optional[list] = None) -> str:
        messages = list(context or [])
        messages.append({"role": "user", "content": prompt})
        resp = httpx.post(
            f"{self._base}/v1/messages",
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 1024,
                "messages": messages,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # Anthropic 响应:content 是 [{type:"text", text:...}] 块列表
        parts = [b.get("text", "") for b in data.get("content", [])
                 if b.get("type") == "text"]
        return "".join(parts).strip()


class MockBackend:
    """测试/离线用:不调真模型,按规则返回固定判断。

    规则:prompt 里出现「连推」信号就开口,否则沉默。让管道可测、可演示。
    """

    def __init__(self, reply: str = "这个任务卡了几回了,是遇到什么坎了吗?"):
        self._reply = reply
        self.calls = []                     # 记录每次 prompt,供测试断言

    def judge(self, prompt: str, context: Optional[list] = None) -> str:
        self.calls.append(prompt)
        return self._reply
