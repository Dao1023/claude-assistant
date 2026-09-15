"""测试:标签层级(core/tags.py)——树构建、子孙展开、防环、删除提升、重名。"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, tags

TODAY = datetime.now().date()


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """每个测试独立临时 DB(内存版 tags 逻辑,不挂 HTTP)。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    c = db.connect()
    yield c
    c.close()


def _task(conn, title, tag_names=(), done=False):
    tid = db.add_task(conn, title=title, drive="end", created=0,
                      deadline=f"{TODAY} 23:59",
                      tags=tag_names)
    if done:
        db.set_status(conn, tid, "done")
    return tid


def _id(conn, name):
    return conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()["id"]


# ---------- create ----------

def test_create_root_and_child(conn):
    root = tags.create(conn, "工作")
    child = tags.create(conn, "科研", root)
    assert tags.tree(conn)[0]["children"][0]["id"] == child


def test_create_dup_name_rejected(conn):
    tags.create(conn, "工作")
    with pytest.raises(ValueError, match="已存在"):
        tags.create(conn, "工作")


def test_create_blank_name_rejected(conn):
    with pytest.raises(ValueError, match="不能为空"):
        tags.create(conn, "  ")


def test_create_missing_parent_rejected(conn):
    with pytest.raises(LookupError):
        tags.create(conn, "孤儿", 999)


# ---------- flat(筛选栏数据源) ----------

def test_flat_parent_by_name_and_active_filter(conn):
    root = tags.create(conn, "工作")
    tags.create(conn, "科研", root)
    _task(conn, "论文", ["科研"])
    _task(conn, "健身", ["健康"])           # 「健康」 tag 随之自动创建
    flat = tags.flat(conn)
    by_name = {t["name"]: t["parent"] for t in flat}
    assert by_name == {"工作": None, "科研": "工作", "健康": None}


def test_flat_includes_parent_with_only_grandchild_tasks(conn):
    # 「工作」自己没有直接任务,但孙辈有 → 应出现(否则筛不到它)
    root = tags.create(conn, "工作")
    mid = tags.create(conn, "科研", root)
    tags.create(conn, "论文", mid)
    _task(conn, "写论文", ["论文"])
    names = [t["name"] for t in tags.flat(conn)]
    assert names == ["工作", "科研", "论文"]   # 单链,全含


def test_flat_includes_idle_tags(conn):
    # 全量语义:只挂在 done 任务上的「过期」也要在(表单要能选到),排进列表
    _task(conn, "旧任务", ["过期"], done=True)
    _task(conn, "现役", ["健康"])
    flat = tags.flat(conn)
    by_name = {t["name"]: t["parent"] for t in flat}
    assert by_name == {"过期": None, "健康": None}
    # 活跃的在前面,闲置的沉底
    assert [t["name"] for t in flat] == ["健康", "过期"]


def test_flat_sorted_by_subtree_active_count(conn):
    _task(conn, "a", ["健康"])
    _task(conn, "b", ["健康"])
    root = tags.create(conn, "工作")
    tags.create(conn, "科研", root)
    _task(conn, "c", ["科研"])
    names = [t["name"] for t in tags.flat(conn)]
    assert names[0] == "健康"                  # 2 > 1(子树活跃数)


# ---------- descendants ----------

def test_descendants_arbitrary_depth(conn):
    a = tags.create(conn, "A")
    b = tags.create(conn, "B", a)
    c = tags.create(conn, "C", b)
    d = tags.create(conn, "D", c)
    assert tags.descendants(conn, a) == {b, c, d}
    assert tags.descendants(conn, c) == {d}
    assert tags.descendants(conn, d) == set()


# ---------- set_parent 防环 ----------

def test_set_parent_basic_and_root(conn):
    a = tags.create(conn, "A")
    b = tags.create(conn, "B")
    tags.set_parent(conn, b, a)
    assert tags.tree(conn)[0]["children"][0]["name"] == "B"
    tags.set_parent(conn, b, None)            # 回根级
    assert len(tags.tree(conn)) == 2


def test_set_parent_self_rejected(conn):
    a = tags.create(conn, "A")
    with pytest.raises(ValueError, match="环"):
        tags.set_parent(conn, a, a)


def test_set_parent_descendant_rejected(conn):
    a = tags.create(conn, "A")
    b = tags.create(conn, "B", a)
    c = tags.create(conn, "C", b)
    with pytest.raises(ValueError, match="环"):
        tags.set_parent(conn, a, c)           # A 挂到自己的孙辈下


def test_set_parent_missing_rejected(conn):
    a = tags.create(conn, "A")
    with pytest.raises(LookupError):
        tags.set_parent(conn, a, 999)


# ---------- rename ----------

def test_rename_and_dup(conn):
    a = tags.create(conn, "A")
    tags.rename(conn, a, "工作")
    assert _id(conn, "工作") == a
    b = tags.create(conn, "B")
    with pytest.raises(ValueError, match="已存在"):
        tags.rename(conn, b, "工作")


# ---------- delete(子标签提升) ----------

def test_delete_promotes_children_and_unlinks_tasks(conn):
    root = tags.create(conn, "工作")
    mid = tags.create(conn, "科研", root)
    leaf = tags.create(conn, "论文", mid)
    tid = _task(conn, "写论文", ["论文"])
    tags.delete(conn, mid)
    # 论文 → 提升到工作下
    t = tags.tree(conn)
    assert [c["name"] for c in t[0]["children"]] == ["论文"]
    assert t[0]["children"][0]["id"] == leaf
    # 任务断的是被删的 mid,论文关联保留
    assert conn.execute("SELECT COUNT(*) c FROM task_tags WHERE task_id=?",
                        (tid,)).fetchone()["c"] == 1


def test_delete_root_child_becomes_root(conn):
    root = tags.create(conn, "工作")
    child = tags.create(conn, "科研", root)
    tags.delete(conn, root)
    names = [n["name"] for n in tags.tree(conn)]
    assert names == ["科研"]
    assert tags.tree(conn)[0]["id"] == child


def test_delete_missing_rejected(conn):
    with pytest.raises(LookupError):
        tags.delete(conn, 999)
