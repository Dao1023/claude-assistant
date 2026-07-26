"""
Claude Assistant - 常驻主动提醒助理

顶层编排:依赖单向 main → app → io → core → config,无环。
watcher 与 tray 通过回调拿 tick,不反向 import。
"""
import threading
import time

from assistant.app.scheduler import tick
from assistant.app.tray import run_tray
from assistant.config import POLL_INTERVAL
from assistant.io.watcher import start_watcher


def scheduler_loop():
    while True:
        tick()
        time.sleep(POLL_INTERVAL)


def main():
    start_watcher(on_change=tick)          # 文件变了 → tick(回调注入)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Claude Assistant 已启动,盯信箱中…")
    tick()                                  # 启动先检查一遍
    run_tray(on_check=tick)                 # 托盘阻塞主线程


if __name__ == "__main__":
    main()
