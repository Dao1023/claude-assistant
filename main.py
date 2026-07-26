"""
Claude Assistant - 常驻主动提醒助理

顶层编排:依赖单向 main → app → io → core → config,无环。
watcher 与 tray 通过回调拿 tick,不反向 import。

每轮循环:
1. 处理 commands.json 新指令(add/done/update/... → SQLite)
2. 处理 inbox.json 提醒(V1 通道)
3. 跑 pusher:按重要性从 SQLite 挑任务推送(写 push_log)
"""
import threading
import time

from assistant.app.scheduler import tick as inbox_tick
from assistant.app.tray import run_tray
from assistant.config import POLL_INTERVAL
from assistant.core import commands, db
from assistant.io.notifier import clear_all
from assistant.io.pusher import tick_push
from assistant.io.watcher import start_watcher


def tick():
    """一轮完整调度。"""
    db.init_db()
    commands.process_commands()   # 新指令 → SQLite
    inbox_tick()                  # V1 inbox 提醒
    tick_push()                   # SQLite 任务推送


def scheduler_loop():
    while True:
        tick()
        time.sleep(POLL_INTERVAL)


def main():
    db.init_db()
    start_watcher(on_change=tick)          # 文件变了 → tick(回调注入)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Claude Assistant 已启动(任务系统 + 推送生命周期)…")
    tick()                                  # 启动先跑一轮
    run_tray(on_check=tick, on_exit=clear_all)  # 托盘阻塞;退出时清通知


if __name__ == "__main__":
    main()
