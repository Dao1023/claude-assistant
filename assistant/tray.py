"""系统托盘"""
import pystray
from PIL import Image, ImageDraw

from .config import APP_NAME
from .scheduler import tick


def make_icon():
    img = Image.new("RGB", (64, 64), (34, 34, 34))
    d = ImageDraw.Draw(img)
    d.ellipse((14, 14, 50, 50), fill=(120, 180, 255))
    return img


def run_tray():
    icon = pystray.Icon("claude-assistant", make_icon(), APP_NAME)
    icon.menu = pystray.Menu(
        pystray.MenuItem("立即检查", lambda: tick()),
        pystray.MenuItem("退出", lambda: icon.stop()),
    )
    icon.run()
