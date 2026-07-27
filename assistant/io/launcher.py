"""唤起 Claude Code"""
import subprocess

from ..config import CLAUDE_EXE, VAULT


def launch_claude(msg=None):
    """打开一个干净的 Claude Code 窗口(开在 Obsidian 库,已信任,免确认)。

    只打开,不塞对话:提醒内容已通过通知本身传达,会话由用户自己 /resume 决定。
    msg 参数保留以兼容旧调用,但不再注入 prompt。
    """
    try:
        # 参数列表 + start 起新窗口,避免 shell 引号嵌套解析问题
        subprocess.Popen(
            ["cmd", "/c", "start", "Claude Assistant", CLAUDE_EXE],
            cwd=VAULT,
        )
    except Exception as e:
        print("唤起失败:", e)
