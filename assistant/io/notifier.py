"""系统通知弹窗"""
from datetime import datetime

from windows_toasts import Toast, WindowsToaster

from ..config import APP_NAME
from ..core.inbox import set_status
from .launcher import launch_claude

toaster = WindowsToaster(APP_NAME)


def clear_all():
    """清掉本 APP 已发出的所有缓存通知(退出/出错时调用,避免残留轰炸)。"""
    try:
        toaster.clear_toasts()
    except Exception as e:
        print("清除通知失败:", e)


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


_STAGE_PREFIX = {"gentle": "提醒", "escalating": "催办", "crisis": "紧急"}


def notify_task(task, stage):
    """任务推送:直接弹窗,不经过 inbox 文件(避免触发 watcher 连锁)。

    点击后只打开一个干净的 Claude Code 窗口(不塞对话),由用户自己 /resume 处理。
    """
    msg = f"[{_STAGE_PREFIX.get(stage, '提醒')}] {task['title']}"
    toast = Toast()
    toast.text_fields = [APP_NAME, msg]

    def on_activated(_):
        launch_claude()

    toast.on_activated = on_activated
    toaster.show_toast(toast)
    print(f"[{datetime.now():%H:%M:%S}] 已弹窗: {msg}")
