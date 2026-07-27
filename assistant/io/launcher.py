"""唤起外部程序:Claude Code、WebUI 面板(chrome --app)。"""
import subprocess
import threading

from ..config import CHROME_EXE, CLAUDE_EXE, VAULT, WEB_PORT


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


# ---- WebUI 面板 ----

_server_lock = threading.Lock()
_server_started = False


def _ensure_server():
    """确保 FastAPI 面板服务在跑(幂等,只起一次,daemon 线程)。"""
    global _server_started
    with _server_lock:
        if _server_started:
            return
        from .server import run           # 延迟 import,避免拖慢主程序启动
        threading.Thread(target=run, args=(WEB_PORT,), daemon=True).start()
        _server_started = True


def open_panel():
    """打开(或唤起)WebUI 面板:先确保服务在跑,再用 chrome --app 开独立窗口。

    --app 模式:无地址栏、独立任务栏图标,像个原生小应用。
    """
    _ensure_server()
    url = f"http://127.0.0.1:{WEB_PORT}/"
    try:
        subprocess.Popen([CHROME_EXE, f"--app={url}"])
    except Exception as e:
        print("打开面板失败:", e)
