"""系统托盘。

解耦:tray 不直接 import scheduler,而是通过回调拿 tick,便于替换/测试。
"""
import pystray
from PIL import Image, ImageDraw

from ..config import APP_NAME


def make_icon():
    img = Image.new("RGB", (64, 64), (34, 34, 34))
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill=(120, 180, 255))
    return img


def run_tray(on_check, on_exit=None):
    """启动托盘。on_check:点'立即检查';on_exit:退出前回调(如清理通知)。"""
    icon = pystray.Icon("claude-assistant", make_icon(), APP_NAME)

    def _quit():
        if on_exit:
            on_exit()
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("立即检查", lambda: on_check()),
        pystray.MenuItem("退出", _quit),
    )
    icon.run()
