"""watchdog 监听信箱变更"""
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import BASE, INBOX
from .scheduler import tick


class InboxHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if Path(event.src_path) == INBOX:
            tick()


def start_watcher():
    observer = Observer()
    observer.schedule(InboxHandler(), str(BASE), recursive=False)
    observer.start()
    return observer
