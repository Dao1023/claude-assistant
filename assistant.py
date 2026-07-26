"""
Claude Assistant - 常驻主动提醒助理 (V1 最小原型)

Claude Code 的外部哑终端:盯信箱 → 到点弹窗 → 点击唤起 Claude Code → 回写状态。
通信契约 = inbox.json。
"""
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from windows_toasts import Toast, WindowsToaster

BASE = Path(__file__).parent
INBOX = BASE / "inbox.json"
CLAUDE_EXE = r"C:\Users\Dao\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe\claude.exe"
VAULT = r"C:\Obsidian"  # 唤起时的工作目录(Obsidian 库)

toaster = WindowsToaster("Claude Assistant")


# ---------- 信箱读写 ----------

def load_inbox():
    try:
        return json.loads(INBOX.read_text(encoding="utf-8"))
    except Exception:
        return {"reminders": []}


def save_inbox(data):
    INBOX.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_status(rid, status, note=""):
    data = load_inbox()
    for r in data["reminders"]:
        if r["id"] == rid:
            r["status"] = status
            if note:
                r["note"] = note
    save_inbox(data)


# ---------- 唤起 Claude Code ----------

def launch_claude(msg):
    """打开 Claude Code 并带上一句开场白,接续对话。"""
    opener = f"助理提醒:{msg}(我们继续)"
    try:
        # 用参数列表 + start 起新窗口,避免 shell 引号嵌套解析问题
        # cwd 设为 Obsidian 库,让 claude 直接开在仓库里(且该目录已被信任,不再弹确认)
        subprocess.Popen(
            ["cmd", "/c", "start", "Claude Assistant", CLAUDE_EXE, opener],
            cwd=VAULT,
        )
    except Exception as e:
        print("唤起失败:", e)


# ---------- 弹窗 ----------

def notify(reminder):
    rid, msg = reminder["id"], reminder["msg"]
    toast = Toast()
    toast.text_fields = ["Claude Assistant", msg]

    def on_activated(_):
        set_status(rid, "done", "用户点击,唤起 Claude Code")
        launch_claude(msg)

    toast.on_activated = on_activated
    toaster.show_toast(toast)
    set_status(rid, "notified")
    print(f"[{datetime.now():%H:%M:%S}] 已弹窗: {msg}")


# ---------- 调度:检查哪些提醒该弹了 ----------

def due(reminder):
    if reminder.get("status") != "pending":
        return False
    t = reminder.get("time", "").strip()
    if not t:  # 空时间 = 立即
        return True
    try:
        return datetime.now() >= datetime.strptime(t, "%Y-%m-%d %H:%M")
    except ValueError:
        return False


def tick():
    data = load_inbox()
    fired = False
    for r in data["reminders"]:
        if due(r):
            notify(r)
            fired = True
    return fired


# ---------- 监听信箱变更 ----------

class InboxHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if Path(event.src_path) == INBOX:
            tick()


def start_watcher():
    observer = Observer()
    observer.schedule(InboxHandler(), str(BASE), recursive=False)
    observer.start()
    return observer


# ---------- 托盘 ----------

def make_icon():
    img = Image.new("RGB", (64, 64), (34, 34, 34))
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill=(120, 180, 255))
    return img


def run_tray():
    icon = pystray.Icon("claude-assistant", make_icon(), "Claude Assistant")
    icon.menu = pystray.Menu(
        pystray.MenuItem("立即检查", lambda: tick()),
        pystray.MenuItem("退出", lambda: icon.stop()),
    )
    icon.run()


# ---------- 主流程 ----------

def scheduler_loop():
    while True:
        tick()
        time.sleep(30)


def main():
    start_watcher()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print("Claude Assistant 已启动,盯信箱中…")
    tick()  # 启动先检查一遍
    run_tray()  # 托盘阻塞主线程


if __name__ == "__main__":
    main()
