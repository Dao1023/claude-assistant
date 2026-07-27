"""测试 InteractableWindowsToaster 的点击回调能否触发。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from windows_toasts import InteractableWindowsToaster, Toast

toaster = InteractableWindowsToaster("Claude Assistant")
toast = Toast()
toast.text_fields = ["点击测试", "点我,看控制台有没有输出 '已点击'"]

def on_activated(event):
    print(">>> 已点击!回调触发成功 <<<", flush=True)

toast.on_activated = on_activated
toaster.show_toast(toast)
print("通知已发,请点击它(保持本窗口开着)...", flush=True)

# 保持进程存活,等点击回调
import time
try:
    for _ in range(60):
        time.sleep(1)
except KeyboardInterrupt:
    pass
