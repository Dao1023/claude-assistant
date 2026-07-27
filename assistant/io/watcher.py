"""watchdog 监听信箱变更。

解耦:watcher 在 io 层,不能 import app 层的 scheduler。
因此 tick 通过回调注入(start_watcher(on_change)),由 app/main 把 tick 传进来。
"""
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..config import DATA, INBOX


class InboxHandler(FileSystemEventHandler):
    def __init__(self, on_change):
        self._on_change = on_change

    def on_modified(self, event):
        if Path(event.src_path) == INBOX:
            self._on_change()


def start_watcher(on_change):
    """启动监听。on_change:文件变更时调用的回调(通常是 app 层的 tick)。"""
    observer = Observer()
    observer.schedule(InboxHandler(on_change), str(DATA), recursive=False)
    observer.start()
    return observer
