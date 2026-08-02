"""全程序退出协调。

托盘是软件门面:点"退出"应带走整个程序,而不是只摘图标留一堆后台线程。

设计:退出必须由主线程(tkinter)发起,因为 tk 的 quit/destroy 只能在创建它的线程调。
托盘子线程只能"发信号"(request_quit);主线程 UI 循环周期轮询该标志,发现后执行
真正的清理与强制退出。daemon 线程(调度/服务)随 os._exit 一并终止。
"""
import os
import threading
import time

_quit_event = threading.Event()
_cleanup = None          # 主线程退出前执行的清理回调(可选,main 注册)


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
    """主线程 UI 循环周期调用:若收到退出请求,清理并强制退出整个进程。"""
    if not quit_requested():
        return
    if _cleanup:
        try:
            _cleanup()
        except Exception:
            pass
    time.sleep(0.1)          # 给清理一点落盘时间
    os._exit(0)              # 强制退出,带走所有 daemon 线程与子线程
