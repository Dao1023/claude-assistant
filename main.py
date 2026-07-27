"""
Claude Assistant - 常驻主动提醒助理

线程模型(tkinter 必须主线程):
- 主线程:tkinter UI 事件循环(催办小卡)
- 子线程:pystray 托盘、调度循环、watchdog 监听

依赖单向 main → app → io → core → config,无环。

每轮调度:
1. 处理 commands.json 新指令(add/done/update/... → SQLite)
2. 处理 inbox.json 提醒(V1 通道)
3. 跑 pusher:按重要性挑任务,弹催办小卡(写 push_log)
"""
import threading
import time

from assistant.app.scheduler import tick as inbox_tick
from assistant.app.tray import run_tray
from assistant.config import POLL_INTERVAL
from assistant.core import commands, db
from assistant.io.launcher import open_panel
from assistant.io.notifier import clear_all
from assistant.io.popup import start_ui
from assistant.io.pusher import tick_push
from assistant.io.watcher import start_watcher

_tick_lock = threading.Lock()


def tick():
    """一轮完整调度。加锁防重入(watcher/scheduler/启动可能并发触发)。"""
    if not _tick_lock.acquire(blocking=False):
        return                            # 上一轮没跑完,跳过本次
    try:
        db.init_db()
        commands.process_commands()   # 新指令 → SQLite
        inbox_tick()                  # V1 inbox 提醒
        tick_push()                   # SQLite 任务推送(弹小卡)
    finally:
        _tick_lock.release()


def scheduler_loop():
    while True:
        tick()
        time.sleep(POLL_INTERVAL)


def main():
    db.init_db()
    start_watcher(on_change=tick)                           # 文件变了 → tick
    threading.Thread(target=scheduler_loop, daemon=True).start()
    # 托盘放子线程(主线程让给 tkinter);左键单击 = 打开 WebUI 面板
    # 退出时 clear_all 清掉 Windows 通知队列残留,避免"进程没了通知还在"
    threading.Thread(
        target=lambda: run_tray(on_check=tick, on_open=open_panel, on_exit=clear_all),
        daemon=True).start()
    print("Claude Assistant 已启动(催办小卡 + 推送生命周期 + WebUI 面板)…")
    tick()                                   # 启动先跑一轮
    start_ui()                               # 主线程:tkinter 事件循环(阻塞)


if __name__ == "__main__":
    main()
