"""系统通知弹窗"""
from datetime import datetime

from windows_toasts import Toast, WindowsToaster

from .config import APP_NAME
from .inbox import set_status
from .launcher import launch_claude

toaster = WindowsToaster(APP_NAME)


def notify(reminder):
    rid, msg = reminder["id"], reminder["msg"]
    toast = Toast()
    toast.text_fields = [APP_NAME, msg]

    def on_activated(_):
        set_status(rid, "done", "用户点击,唤起 Claude Code")
        launch_claude(msg)

    toast.on_activated = on_activated
    toaster.show_toast(toast)
    set_status(rid, "notified")
    print(f"[{datetime.now():%H:%M:%S}] 已弹窗: {msg}")
