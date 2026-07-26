"""
Claude Assistant - 常驻主动提醒助理

入口:启动监听 + 调度 + 托盘。
"""
import threading
import time

from assistant.config import POLL_INTERVAL
from assistant.scheduler import tick
from assistant.tray import run_tray
from assistant.watcher import start_watcher


def scheduler_loop():
    while True:
        tick()
        time.sleep(POLL_INTERVAL)


def main():
    start_watcher()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Claude Assistant 已启动,盯信箱中…")
    tick()  # 启动先检查一遍
    run_tray()  # 托盘阻塞主线程


if __name__ == "__main__":
    main()
