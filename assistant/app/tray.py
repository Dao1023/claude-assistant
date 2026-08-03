"""系统托盘。

解耦:tray 不直接 import scheduler,而是通过回调拿 tick,便于替换/测试。

另开一个隐藏窗口线程监听 TaskbarCreated:explorer 重启/崩溃后系统会清掉所有
托盘图标并广播该消息,pystray 不会自动重建,需手动再注册一次,否则"进程还在、
托盘消失"(用户找不到入口)。
"""
import ctypes
import threading
from ctypes import wintypes

import pystray
from PIL import Image, ImageDraw

from ..config import APP_NAME
from ..io import notify_window
from . import lifecycle

WM_NULL = 0x0000


def make_icon():
    img = Image.new("RGB", (64, 64), (34, 34, 34))
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill=(120, 180, 255))
    return img


def _refresh(icon):
    """explorer 重启后重新注册托盘图标。

    pystray 图标仍在运行,update_menu 走 NIM_MODIFY;图标已被系统清掉时
    MODIFY 失败,pystray 自动回退 NIM_ADD 重建。
    """
    try:
        icon.update_menu()
    except Exception:
        pass


def _taskbar_created_watcher(icon):
    """常驻隐藏窗口:收到 TaskbarCreated 广播就重建托盘图标。"""
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_long, wintypes.HWND, ctypes.c_uint,
        wintypes.WPARAM, wintypes.LPARAM)
    taskbar_created = u32.RegisterWindowMessageW("TaskbarCreated")

    def _proc(hwnd, msg, wp, lp):
        if msg == taskbar_created:
            _refresh(icon)
        return u32.DefWindowProcW(hwnd, msg, wp, lp)

    proc = WNDPROC(_proc)               # 必须持有引用,防 GC 回收回调

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HANDLE),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.hInstance = k32.GetModuleHandleW(None)
    wc.lpszClassName = "ClaudeAssistantTrayWatcher"
    if not u32.RegisterClassW(ctypes.byref(wc)):
        return                          # 注册失败则放弃重建,托盘照常工作
    hwnd = u32.CreateWindowExW(0, wc.lpszClassName, "ClaudeAssistantTrayWatcher",
                               0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
    if not hwnd:
        return

    msg = wintypes.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        u32.TranslateMessage(ctypes.byref(msg))
        u32.DispatchMessageW(ctypes.byref(msg))


def run_tray(on_open=None):
    """启动托盘。on_open:打开 WebUI 面板(左键单击 = default 项)。"""
    icon = pystray.Icon("claude-assistant", make_icon(), APP_NAME)

    def _quit():
        # 退出 = 带走整个程序:请求主线程执行全程序退出
        icon.stop()
        lifecycle.request_quit()

    # 左键单击触发 default 项(打开面板);菜单里也保留入口作退路
    open_item = pystray.MenuItem("打开面板", lambda: on_open and on_open(),
                                 default=True, visible=on_open is not None)
    # 手动唤出待办浮窗(通知来了自动弹,这里给「随时想看」的入口)。
    # notify_window.show 是队列式跨线程信号,托盘线程直接调安全。
    show_item = pystray.MenuItem("显示待办窗", lambda: notify_window.show())
    icon.menu = pystray.Menu(
        open_item,
        show_item,
        pystray.MenuItem("退出", _quit),
    )
    threading.Thread(target=_taskbar_created_watcher,
                     args=(icon,), daemon=True).start()
    icon.run()
