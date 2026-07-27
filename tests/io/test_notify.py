"""对照测试:V1 notify vs notify_task,看点击回调是否触发。进程保持存活。"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant.io.notifier import notify, notify_task

# 发一个 V1 风格的(走 inbox reminder 结构)
notify({"id": "test-v1", "msg": "【V1 notify】点我试试"})
# 发一个 notify_task 风格的
notify_task({"id": "t1", "title": "【notify_task】点我试试"}, "gentle")

print("两条通知已发(V1 notify + notify_task),进程保持 40 秒,请分别点击...", flush=True)
try:
    for _ in range(40):
        time.sleep(1)
except KeyboardInterrupt:
    pass
print("测试结束", flush=True)
