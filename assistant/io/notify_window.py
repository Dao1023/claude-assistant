"""通知浮窗:pywebview 无框置顶小窗,替代原 tkinter 小卡(io/popup 已删)。

为什么换栈:tkinter 手写坐标布局易碎(卡片变高即错位)、丑、交互弱。
改为:浮窗只是个壳,内容是 FastAPI 的 /notify 页(复用面板 Vue 前端),
按钮走已测过的 REST API。样式/交互归前端,本模块只管窗口生命周期。

线程模型(与原 tkinter 同构,故托盘/调度/面板子线程不用动):
- 主线程:webview.start() GUI 事件循环(start_ui,阻塞)。
- 开窗请求经队列 _requests 从任意线程(调度/pusher)传入;
  start() 的 func 钩子起一个消费线程,把请求派回 GUI 线程开窗。
  pywebview 的 create_window 在 start() 运行后从非 GUI 线程调用是支持的,
  但用队列串行化可避免并发开窗竞争,最稳。

单例:同一时刻只开一个通知窗。新通知来时,窗已开则让前端自己刷新
(/notify 页轮询 /api/tasks),不重复开窗;窗被关则 _win 置 None,下次重开。
"""
import queue
import threading

import webview

from ..config import WEB_PORT

_W, _H = 380, 520          # 浮窗尺寸(无框,内容自适应滚动)
_MARGIN = 16

_requests = queue.Queue()  # 跨线程开窗信号(内容无需携带,前端拉数据)
_win = None                # 当前通知窗(Window 或 None)
_lock = threading.Lock()


def _notify_url():
    return f"http://127.0.0.1:{WEB_PORT}/notify"


def _open_window():
    """在 GUI 线程开(或聚焦)通知浮窗。右下角、无框、置顶、可拖、圆角阴影。"""
    global _win
    with _lock:
        if _win is not None:
            try:
                _win.show()
                _win.on_top = True
            except Exception:
                _win = None
        if _win is None:
            screen = webview.screens[0]
            x = screen.width - _W - _MARGIN
            y = screen.height - _H - _MARGIN - 48   # 避开任务栏
            _win = webview.create_window(
                "待办", _notify_url(),
                width=_W, height=_H, x=x, y=y,
                frameless=True, on_top=True, easy_drag=True,
                resizable=False, shadow=True,
            )
            _win.events.closed += _on_closed


def _on_closed():
    """用户关了浮窗:清引用,下次通知重开。"""
    global _win
    with _lock:
        _win = None


def _consume():
    """消费开窗信号:GUI 就绪后由 start() 的 func 钩子启动,阻塞等信号。"""
    while True:
        _requests.get()
        try:
            _open_window()
        except Exception as e:                    # 开窗失败不拖垮消费者
            print(f"[notify_window] 开窗失败: {e}")


def show():
    """从任意线程请求弹出通知浮窗(幂等:已开则聚焦)。"""
    _requests.put(True)


def start_ui():
    """主线程入口:起 webview GUI 循环(阻塞)。托盘/调度在子线程,先就绪再调本函数。

    func 钩子在 GUI 初始化完成后回调,那里起消费线程——保证 create_window
    调用时 GUI 已就绪。
    """
    webview.start(func=lambda: threading.Thread(target=_consume, daemon=True).start())
