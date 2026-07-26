"""唤起 Claude Code"""
import subprocess

from .config import CLAUDE_EXE, VAULT


def launch_claude(msg):
    """打开 Claude Code,开在 Obsidian 库(已信任,免确认)。"""
    opener = f"助理提醒:{msg}(我们继续)"
    try:
        # 参数列表 + start 起新窗口,避免 shell 引号嵌套解析问题
        subprocess.Popen(
            ["cmd", "/c", "start", "Claude Assistant", CLAUDE_EXE, opener],
            cwd=VAULT,
        )
    except Exception as e:
        print("唤起失败:", e)
