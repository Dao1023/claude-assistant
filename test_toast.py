"""最小可行性测试:弹一个系统通知"""
from windows_toasts import Toast, WindowsToaster

toaster = WindowsToaster("Claude Assistant")
toast = Toast()
toast.text_fields = ["测试提醒", "如果你看到这个,说明弹窗可行 ✅"]
toast.on_activated = lambda _: print("用户点击了通知!")

toaster.show_toast(toast)
print("toast sent")
