"""全程序退出协调。

托盘是软件门面:点"退出"应带走整个程序,而不是只摘图标留一堆后台线程。

设计:托盘子线程只"发信号"(request_quit)。退出执行用 os._exit 强杀整个进程,
不依赖特定 UI 线程,故轮询可放独立 daemon 线程(watch_quit),由 main 启动;
daemon 线程(调度/服务/托盘)随 os._exit 一并终止。
"""
import os
import threading
import time

_quit_event = threading.Event()
_cleanup = None          # 退出前执行的清理回调(可选,main 注册)


def register_cleanup(fn):
    """main 启动时注册清理回调(可选;当前无 V1 资源需清理,留扩展口)。"""
    global _cleanup
    _cleanup = fn


def request_quit():
    """任意线程(托盘子线程)调用:请求全程序退出。"""
    _quit_event.set()


def quit_requested():
    return _quit_event.is_set()


def poll_and_quit():
    """若收到退出请求,清理并强制退出整个进程。供轮询调用。"""
    if not quit_requested():
        return
    if _cleanup:
        try:
            _cleanup()
        except Exception:
            pass
    time.sleep(0.1)          # 给清理一点落盘时间
    os._exit(0)              # 强制退出,带走所有 daemon 线程与子线程


def watch_quit(interval=0.3):
    """退出看门线程:周期检查退出标志。main 以 daemon 线程启动,替代原 tk 循环轮询。

    os._exit 强杀不依赖主线程,故轮询放 daemon 线程即可;主线程让给 webview GUI 循环。
    """
    while True:
        poll_and_quit()
        time.sleep(interval)
