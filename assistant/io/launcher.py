"""唤起外部程序:Claude Code、WebUI 面板(chrome --app)。"""
import socket
import subprocess
import threading
import time

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
_actual_port = None                     # 服务实际监听的端口(自动顺延后的结果)

MAX_PORT_TRIES = 20                     # 从 WEB_PORT 起最多往后顺延几个口


def _port_free(port):
    """该端口能否绑定(空闲)?用 bind 探测——比 connect 准,
    能识别代理软件那种 'Bound 但未 Listen' 的占用(如 mihomo)。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _pick_port():
    """从 WEB_PORT 起找第一个空闲端口。全被占则抛错。"""
    for i in range(MAX_PORT_TRIES):
        port = WEB_PORT + i
        if _port_free(port):
            return port
    raise RuntimeError(f"{WEB_PORT}~{WEB_PORT + MAX_PORT_TRIES - 1} 端口全被占用")


def _server_thread(port):
    """服务线程入口:包住 run,把异常写进日志文件。

    关键:子线程异常默认被静默吞掉(pythonw 无窗口更看不见),
    必须落盘才能诊断"服务为什么没起来"。
    """
    import traceback
    from ..config import DATA
    log = DATA / "panel_server.log"
    try:
        from .server import run
        run(port)
    except Exception:
        log.write_text(traceback.format_exc(), encoding="utf-8")


def _ensure_server():
    """确保 FastAPI 面板服务在跑(幂等,只起一次,daemon 线程)。

    端口自动顺延:从 WEB_PORT 起找第一个空闲口,记录到 _actual_port,
    供 open_panel 用同一个号开浏览器,保证服务与面板永远对上。
    """
    global _server_started, _actual_port
    with _server_lock:
        if _server_started:
            return
        _actual_port = _pick_port()
        threading.Thread(target=_server_thread, args=(_actual_port,), daemon=True).start()
        _server_started = True
        if _actual_port != WEB_PORT:
            print(f"端口 {WEB_PORT} 被占,面板服务顺延到 {_actual_port}")


def _wait_port(port, timeout=5.0):
    """轮询等待端口真正可连接(服务 listen 完成),超时返回 False。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True                     # 端口可连,服务就绪
        except OSError:
            time.sleep(0.05)                    # 还没好,50ms 后再试
    return False


def open_panel():
    """打开(或唤起)WebUI 面板:起服务后立刻用 chrome --app 开独立窗口。

    --app 模式:无地址栏、独立任务栏图标,像个原生小应用。
    不阻塞等服务就绪——浏览器先开,服务 1 秒左右起来,刷新一下即可(体感秒开)。
    """
    _ensure_server()
    url = f"http://127.0.0.1:{_actual_port}/"
    try:
        subprocess.Popen([CHROME_EXE, f"--app={url}"])
    except Exception as e:
        print("打开面板失败:", e)
