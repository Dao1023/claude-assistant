"""测试催办小卡:弹三档各一张,验证样式与按钮。"""
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant.ui import popup


def done():
    print(">>> 点了【完成】", flush=True)


def snooze():
    print(">>> 点了【稍后/关窗】", flush=True)


def ai():
    print(">>> 点了【找AI】", flush=True)


def emit():
    time.sleep(0.5)
    popup.show_task_card({"id": "1", "title": "【提醒】一周没联系的发小"}, "gentle", done, snooze, ai)
    time.sleep(0.3)
    popup.show_task_card({"id": "2", "title": "【催办】YFPO 报价单还没发"}, "escalating", done, snooze, ai)
    time.sleep(0.3)
    popup.show_task_card({"id": "3", "title": "【紧急】今天 18:00 截止的项目交付"}, "crisis", done, snooze, ai)


threading.Thread(target=emit, daemon=True).start()
print("弹出 3 张小卡(温和/催办/紧急),试试点按钮和关窗...", flush=True)
popup.start_ui()  # 主线程跑 UI(阻塞)
