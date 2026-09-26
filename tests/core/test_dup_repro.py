"""复现:每日任务跨天出现两份(2026-09-26 报告,修复前的失败证据)。

三条复现路径,全部对应 data/assistant.db 里「日语每日(和豆包)」的真实事故链
(09-20 11:58 与 09-23 22:33 两次 1->2 跳变,之后每天午夜 close_overdue 按份克隆,
N 份永远保持 N 份):

1. 跨天后对旧卡点完成:close_overdue 已关旧任务并克隆新一天实例,
   用户再点浮窗残留卡片上的「完成」,do_done 不查状态,又克隆一份 → 2 份 active。
   (NotifyPage 的卡片只在收到 done/snooze 事件时移除,close_overdue 不发事件,
    昨晚的卡今天仍可点。)
2. 同一 active 任务连续两次 do_done(双击/双端):无认领、无状态守卫 → 2 份克隆。
3. 对已过期但仍 active 的任务点完成:do_done 盲目 +interval,克隆出「出生即过期」
   的实例(库内实证:65b48bb0ead3 created 08-16 17:10:09,deadline 08-15 23:59:59),
   下一轮 close_overdue 再关再克隆,把复制链续下去。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import actions, db

DAY = 86400
NOW = int(time.time())


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """每个测试用独立临时 DB。db.connect() 动态读 config.DB_PATH。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def _add_daily(conn, deadline):
    """建一个每日重复的 end 任务(与库内「日语每日」同构)。"""
    return db.add_task(conn, "每日任务", "end", created=NOW,
                       deadline=deadline, recurrence_interval=DAY)


def _active(conn):
    return [dict(r) for r in db.list_active(conn, "end")]


# ---------- 路径1:跨天后对残留卡点完成 ----------

def test_rollover_then_stale_done_makes_two_copies(conn):
    old = _add_daily(conn, deadline=NOW - 60)      # 昨天的卡,已过点
    actions.close_overdue(conn)                    # 跨天:旧卡关闭 + 克隆今天一份
    assert len(_active(conn)) == 1                 # 此刻正常:只有今天一份
    actions.do_done(conn, {"task_id": old})        # 模拟:点浮窗残留卡上的「完成」
    active = _active(conn)
    ids = ", ".join(t["id"] for t in active)
    assert len(active) == 1, f"出现 {len(active)} 份 active(id: {ids})"


# ---------- 路径2:同一张卡点两次完成 ----------

def test_double_done_on_same_task_makes_two_copies(conn):
    tid = _add_daily(conn, deadline=NOW + DAY)
    actions.do_done(conn, {"task_id": tid})        # 第一次:正常,克隆明天一份
    actions.do_done(conn, {"task_id": tid})        # 第二次(双击/另一端):不该有第二份
    active = _active(conn)
    ids = ", ".join(t["id"] for t in active)
    assert len(active) == 1, f"出现 {len(active)} 份 active(id: {ids})"


# ---------- 路径3:过期任务上点完成,克隆出生即过期 ----------

def test_done_on_overdue_active_clones_born_overdue(conn):
    tid = _add_daily(conn, deadline=NOW - 2 * DAY)  # 拖了两天没开程序,仍 active
    actions.do_done(conn, {"task_id": tid})         # 现在补做,点完成
    rows = conn.execute(
        "SELECT s.deadline FROM tasks t JOIN schedule s ON s.task_id=t.id"
        " WHERE t.status='active'").fetchall()
    assert len(rows) == 1, f"克隆了 {len(rows)} 份"
    assert rows[0]["deadline"] > NOW, \
        f"克隆的 deadline={rows[0]['deadline']} <= now={NOW}:出生即过期,下一轮又会被关闭再克隆"
