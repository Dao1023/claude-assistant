"""通知浮窗:pywebview 无框置顶小窗,替代原 tkinter 小卡(io/popup 已删)。

为什么换栈:tkinter 手写坐标布局易碎(卡片变高即错位)、丑、交互弱。
改为:浮窗只是个壳,内容是 FastAPI 的 /notify 页(复用面板 Vue 前端),
按钮走已测过的 REST API。样式/交互归前端,本模块只管窗口生命周期。

常驻单例 + 隐藏切换(关键):
pywebview 的 start() 之前必须先建至少一个窗口,故启动时建一个 hidden 窗;
有通知 show()、用户点关闭则拦截改为 hide()——窗口常驻不销毁,start() 循环不退。

线程模型(核心架构,别再乱碰):
窗口对象 _win 只能被一个线程碰——专属的「窗口操作 worker」线程。
pywebview 的 show/hide/on_top 全是「封送到 winforms GUI 线程并阻塞等它」的
同步调用:GUI 线程一旦繁忙(渲染页面/处理上一个 Invoke),任何线程的同步
窗口调用都会死锁(曾实锤:_consume 卡在 on_top 的 set_on_top 封送)。
故:js_api 回调、closing 事件、外部 show() 一律只往队列 put 意图,
由 worker 线程串行取出执行——worker 卡了只是 worker 卡,GUI 主线程的消息泵
永远空闲、永远能响应,窗口不可能 Not Responding。
"""
import queue
import threading

import webview

from ..config import WEB_PORT

_W, _H = 720, 560          # 浮窗尺寸(无框,两列:AI 对话 + 待办,内容自适应滚动)
_MARGIN = 16

_ops = queue.Queue()       # 窗口操作意图队列:'show' / 'hide'
_win = None                # 常驻通知窗(Window,创建后不销毁;只有 worker 线程碰)
_ready = threading.Event() # GUI 循环已启动、窗口已建


def _notify_url():
    return f"http://127.0.0.1:{WEB_PORT}/notify"


def _position():
    """右下角定位(主屏,避开任务栏)。"""
    screen = webview.screens[0]
    x = screen.width - _W - _MARGIN
    y = screen.height - _H - _MARGIN - 48
    return x, y


def _do_show():
    """实际显示浮窗(仅 worker 线程调;窗口已建,只切换可见性)。

    只调 show(),绝不再设 on_top:窗口创建时已 on_top=True,重设是多余的;
    且 on_top 的 setter 无 shown 守卫、直接封送到 GUI 线程,启动期 GUI 忙于
    建窗/渲染时,这次封送永远等不到 → win-op 死锁(已实锤多次)。show() 自带
    shown 守卫,是唯一安全的可见性操作。
    """
    if _win is None:
        return
    try:
        _win.show()
    except Exception as e:
        print(f"[notify_window] 显示失败: {e}")


def _do_hide():
    """实际隐藏浮窗(仅 worker 线程调)。"""
    if _win is None:
        return
    try:
        _win.hide()
    except Exception as e:
        print(f"[notify_window] 隐藏失败: {e}")


def _do_resize(w, h):
    """实际调整浮窗大小(仅 worker 线程调)。

    无边框窗口没有系统缩放边,尺寸由设置滑条驱动。resize 同样封送到 GUI
    线程,故必须走 win-op 队列,不能任意线程直调。失败只打印,不影响主流程。
    """
    if _win is None:
        return
    try:
        _win.resize(int(w), int(h))
    except Exception as e:
        print(f"[notify_window] 调整大小失败: {e}")


def _op_worker():
    """窗口操作专属线程:串行消费意图,唯一被允许碰 _win 的业务线程。

    开工前先等窗口 loaded(页面真加载完、GUI 线程空闲),否则启动期抢着
    封送会撞上 GUI 忙碌期 → 死锁。之后每个意图串行执行;某个操作真卡了,
    也只是本线程卡,GUI 主线程照常响应。
    """
    _ready.wait()
    if _win is not None:
        _win.events.loaded.wait(30)      # 等首页面加载完,GUI 线程进入稳定消息循环
    while True:
        op, payload = _ops.get()
        if op == "show":
            _do_show()
        elif op == "hide":
            _do_hide()
        elif op == "resize":
            _do_resize(*payload)


def show():
    """从任意线程请求弹出通知浮窗(幂等)。只投意图,不直接碰窗口。"""
    _ops.put(("show", None))


def hide():
    """从任意线程请求隐藏浮窗(幂等)。只投意图,不直接碰窗口。"""
    _ops.put(("hide", None))


def resize(w, h):
    """从任意线程请求调整浮窗大小。只投意图,不直接碰窗口。"""
    _ops.put(("resize", (int(w), int(h))))


def _on_closing():
    """用户点关闭:不销毁,改为隐藏(窗口常驻,下次通知再 show)。"""
    hide()
    return False                     # 阻止默认关闭(销毁)


class _JsApi:
    """暴露给前端 JS 的接口:浮窗页面的 × 按钮调它隐藏窗口。

    比 window.close() 可靠:pywebview 的 js_api 是显式桥,不依赖
    frameless 下 close 的不确定行为。前端 window.pywebview.api.hide()。
    """
    def hide(self):
        hide()

    def resize(self, w, h):
        """设置滑条调大小 → 投意图到 win-op 队列(本回调跑在 GUI 线程,绝不直碰窗口)。"""
        try:
            resize(int(w), int(h))
        except (TypeError, ValueError) as e:
            print(f"[notify_window] resize 参数非法: {e}")


def start_ui():
    """主线程入口:建常驻浮窗(先隐藏)+ 起 worker + 起 GUI 循环(阻塞)。

    托盘/调度/看门在子线程,先就绪再调本函数。
    """
    global _win
    x, y = _position()
    # 尺寸取自设置(无边框无拖边,宽高由设置滑条持久化),缺省回退常量
    try:
        from ..core import settings as _s
        w = int(_s.get("window_width"))
        h = int(_s.get("window_height"))
    except Exception:
        w, h = _W, _H
    _win = webview.create_window(
        "待办", _notify_url(),
        width=w, height=h, x=x, y=y,
        frameless=True, on_top=True, easy_drag=False,   # 拖拽走前端 pywebview-drag-region 类(顶部)
        resizable=False, shadow=True, hidden=True,   # 启动先隐藏,有通知才 show
        js_api=_JsApi(),
    )
    _win.events.closing += _on_closing
    threading.Thread(target=_op_worker, daemon=True, name="win-op").start()
    _ready.set()
    webview.start()
