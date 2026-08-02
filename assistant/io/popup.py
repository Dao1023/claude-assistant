"""催办小卡:tkinter 自建置顶弹窗。

为什么不用系统 Toast:Toast 收回通知中心后点击失效(无 AUMID),且放不了按钮。
自建小卡:点击 100% 可靠、可放【完成/稍后/找AI】按钮、三档配色、持续存在直到处理。

属于 io 层。tkinter 必须在主线程跑,因此用队列把"弹卡请求"从调度线程传到 UI 线程。
"""
import queue
import tkinter as tk

from ..app import lifecycle
from ..core.actions import snooze_options

# 三档配色(背景 / 标题文字)
_STYLES = {
    "gentle":     {"bg": "#eaf3ff", "bar": "#5b9bd5", "label": "提醒"},
    "escalating": {"bg": "#fff4e0", "bar": "#e8a33d", "label": "催办"},
    "crisis":     {"bg": "#ffe5e5", "bar": "#e05252", "label": "紧急"},
}

_CARD_W, _CARD_H = 320, 130
_MARGIN = 16

# 跨线程队列:(task, stage, callbacks)
_requests = queue.Queue()
_root = None
_open_cards = []          # 已打开的小卡,用于层叠定位


def _place(win):
    """把小卡放到屏幕右下角,已有多张则向上层叠。"""
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    idx = len(_open_cards)
    x = sw - _CARD_W - _MARGIN
    y = win.winfo_screenheight() - (_CARD_H + _MARGIN) * (idx + 1) - 40
    win.geometry(f"{_CARD_W}x{_CARD_H}+{x}+{max(y, 0)}")


def _close(win):
    if win in _open_cards:
        _open_cards.remove(win)
    win.destroy()


def _restack():
    """重新摆放所有打开的小卡(高度变化后调用)。"""
    for i, w in enumerate(_open_cards):
        h = w.winfo_height()
        x = w.winfo_screenwidth() - _CARD_W - _MARGIN
        y = w.winfo_screenheight() - (h + _MARGIN) * (i + 1) - 40
        w.geometry(f"{_CARD_W}x{h}+{x}+{max(y, 0)}")


def _make_card(task, stage, on_done, on_snooze, on_ai):
    style = _STYLES.get(stage, _STYLES["gentle"])
    win = tk.Toplevel(_root)
    win.title("Claude Assistant")
    win.configure(bg=style["bg"])
    win.attributes("-topmost", True)       # 置顶
    win.resizable(False, False)
    _open_cards.append(win)
    _place(win)

    # 顶部色条 + 档位
    tk.Frame(win, bg=style["bar"], height=6).pack(fill="x")
    tk.Label(win, text=style["label"], bg=style["bg"], fg=style["bar"],
             font=("Microsoft YaHei", 9, "bold")).pack(anchor="w", padx=10, pady=(6, 0))
    # 任务标题
    tk.Label(win, text=task["title"], bg=style["bg"], fg="#222",
             font=("Microsoft YaHei", 11), wraplength=_CARD_W - 20,
             justify="left").pack(anchor="w", padx=10, pady=(2, 6))

    # 主按钮行
    btns = tk.Frame(win, bg=style["bg"])
    btns.pack(fill="x", padx=10, pady=(0, 8))

    def _mk(parent, text, cmd, primary=False):
        b = tk.Button(parent, text=text, width=7, relief="flat",
                      bg=style["bar"] if primary else "#ffffff",
                      fg="#ffffff" if primary else "#333333",
                      command=cmd)
        b.pack(side="left", padx=(0, 6))
        return b

    # 时长选项行(默认隐藏,点「稍后」展开)
    opts_row = tk.Frame(win, bg=style["bg"])

    def _do_snooze(until):
        on_snooze(until)
        _close(win)

    def _show_snooze_opts():
        # 已展开则不重复
        if opts_row.winfo_ismapped():
            return
        for _key, (label, until) in snooze_options().items():
            b = tk.Button(opts_row, text=label, width=7, relief="flat",
                          bg="#ffffff", fg="#333333",
                          command=lambda u=until: _do_snooze(u))
            b.pack(side="left", padx=(0, 6))
        opts_row.pack(fill="x", padx=10, pady=(0, 8))
        # 加高小卡容纳选项行
        win.geometry(f"{_CARD_W}x{_CARD_H + 40}")
        _restack()

    _mk(btns, "完成", lambda: (on_done(), _close(win)), primary=True)
    _mk(btns, "稍后", _show_snooze_opts)
    _mk(btns, "找AI", lambda: (on_ai(), _close(win)))

    win.protocol("WM_DELETE_WINDOW", lambda: (on_snooze(None), _close(win)))  # 关窗=稍后(默认 1h)


def _drain():
    """UI 线程:取出队列里的弹卡请求并创建小卡。顺带轮询全程序退出标志。"""
    lifecycle.poll_and_quit()          # 托盘点退出 → 主线程在此执行真正的全退出
    try:
        while True:
            task, stage, cbs = _requests.get_nowait()
            _make_card(task, stage, cbs["done"], cbs["snooze"], cbs["ai"])
    except queue.Empty:
        pass
    _root.after(150, _drain)


def start_ui():
    """在主线程启动 tk 事件循环(阻塞)。"""
    global _root
    _root = tk.Tk()
    _root.withdraw()                       # 隐藏主窗,只用 Toplevel 小卡
    _root.after(150, _drain)
    _root.mainloop()


def show_task_card(task, stage, on_done, on_snooze, on_ai):
    """从任意线程请求弹一张任务小卡。callbacks 在用户点击时于 UI 线程调用。"""
    _requests.put((task, stage, {"done": on_done, "snooze": on_snooze, "ai": on_ai}))
