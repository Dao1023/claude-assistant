"""通知浮窗:pywebview 无框置顶小窗,替代原 tkinter 小卡(io/popup 已删)。

为什么换栈:tkinter 手写坐标布局易碎(卡片变高即错位)、丑、交互弱。
改为:浮窗只是个壳,内容是 FastAPI 的 /notify 页(复用面板 Vue 前端),
按钮走已测过的 REST API。样式/交互归前端,本模块只管窗口生命周期。

线程模型(与原 tkinter 同构,故托盘/调度/面板子线程不用动):
- 主线程:webview.start() GUI 事件循环(start_ui,阻塞)。
- 开窗信号经队列 _requests 从任意线程(调度/pusher)传入;消费线程取出后开窗。

常驻单例 + 隐藏切换(关键):
pywebview 的 start() 之前必须先建至少一个窗口,故启动时建一个 hidden 窗;
有通知 show()、用户点关闭则拦截改为 hide()——窗口常驻不销毁,start() 循环不退。
这正好契合「单例复用」:一个窗,通知来了显示,处理完隐藏,下次通知再显示。
"""
import queue
import threading

import webview

from ..config import WEB_PORT

_W, _H = 380, 520          # 浮窗尺寸(无框,内容自适应滚动)
_MARGIN = 16

_requests = queue.Queue()  # 跨线程开窗信号(内容无需携带,前端拉数据)
_win = None                # 常驻通知窗(Window,创建后不销毁)
_ready = threading.Event() # GUI 循环已启动、窗口已建


def _notify_url():
    return f"http://127.0.0.1:{WEB_PORT}/notify"


def _position():
    """右下角定位(主屏,避开任务栏)。"""
    screen = webview.screens[0]
    x = screen.width - _W - _MARGIN
    y = screen.height - _H - _MARGIN - 48
    return x, y


def _show():
    """显示浮窗并置顶(由消费线程在收到信号时调;窗口已建,只切换可见性)。"""
    if _win is None:
        return
    try:
        _win.show()
        _win.on_top = True
    except Exception as e:
        print(f"[notify_window] 显示失败: {e}")


def _consume():
    """消费开窗信号:阻塞等信号,收到则显示常驻浮窗。"""
    _ready.wait()                    # 等 GUI 起来、窗口建好
    while True:
        _requests.get()
        _show()


def show():
    """从任意线程请求弹出通知浮窗(幂等)。"""
    _requests.put(True)


def _on_closing():
    """用户点关闭:不销毁,改为隐藏(窗口常驻,下次通知再 show)。"""
    if _win is not None:
        _win.hide()
    return False                     # 阻止默认关闭(销毁)


def start_ui():
    """主线程入口:建常驻浮窗(先隐藏)+ 起 GUI 循环(阻塞)。

    托盘/调度/看门在子线程,先就绪再调本函数。
    """
    global _win
    x, y = _position()
    _win = webview.create_window(
        "待办", _notify_url(),
        width=_W, height=_H, x=x, y=y,
        frameless=True, on_top=True, easy_drag=True,
        resizable=False, shadow=True, hidden=True,   # 启动先隐藏,有通知才 show
    )
    _win.events.closing += _on_closing
    _ready.set()
    threading.Thread(target=_consume, daemon=True).start()
    webview.start()
