"""
Claude Assistant - 常驻主动提醒助理

线程模型(webview 必须主线程):
- 主线程:pywebview GUI 事件循环(通知浮窗,io/notify_window)
- 子线程:pystray 托盘、调度循环、面板服务(FastAPI)、退出看门

依赖单向 main → app → io → core → config,无环。

调度:每轮跑 pusher,按重要性挑任务(写 push_log),挑到则触发通知浮窗。
浮窗内容是 FastAPI 的 /notify 页(复用面板 Vue 前端),按钮走 REST API。
轮询间隔读 settings.poll_interval(规则页可配,即改即生效)。

任务增删改查走 HTTP 接口(io/server.py → core/actions.py)。
"""
import threading
import time

from assistant.app.tray import run_tray
from assistant.app import lifecycle
from assistant.core import db, settings
from assistant.io.agent import start_agent
from assistant.io.launcher import _ensure_server, open_panel
from assistant.io.notify_window import start_ui
from assistant.io.pusher import tick_push

_tick_lock = threading.Lock()


def tick():
    """一轮调度:跑任务推送。加锁防重入(轮询/托盘并发)。"""
    if not _tick_lock.acquire(blocking=False):
        return                            # 上一轮没跑完,跳过本次
    try:
        db.init_db()
        tick_push()                       # SQLite 任务推送(触发浮窗)
    finally:
        _tick_lock.release()


def scheduler_loop():
    while True:
        tick()
        time.sleep(settings.get("poll_interval"))


def main():
    db.init_db()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    # 面板服务随启动常驻预热:点托盘时服务已热,open_panel 秒开、零等待、无竞态
    _ensure_server()
    # AI 旁观 Agent(第四层):订阅事件总线,有 key 则用 DeepSeek 判断该不该开口;
    # 无 key 退化为只旁观不开口。daemon 线程,随程序退出。
    start_agent()
    # 托盘退出 = 带走整个程序:托盘子线程发信号,看门线程轮询到后 os._exit 强杀
    lifecycle.register_cleanup(lambda: None)
    threading.Thread(target=lifecycle.watch_quit, daemon=True).start()
    # 托盘放子线程(主线程让给 webview);左键单击 = 打开 WebUI 面板
    threading.Thread(
        target=lambda: run_tray(on_open=open_panel),
        daemon=True).start()
    print("Claude Assistant 已启动(通知浮窗 + 推送生命周期 + WebUI 面板)…")
    tick()                                   # 启动先跑一轮
    start_ui()                               # 主线程:webview GUI 事件循环(阻塞)


if __name__ == "__main__":
    main()
