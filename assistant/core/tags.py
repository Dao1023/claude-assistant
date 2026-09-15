"""标签树:层级关系的读取与维护(邻接表,任意深度单父)。

标签总量几十,读全表在 Python 里递归展开子孙,不上递归 SQL。
层级语义(core/tags.py 独占,别处别自写):
- 隐式继承:任务挂「科研」,筛选「工作」自动命中(筛选在前端做,见 frontend TagFilter)。
- 删除标签:子标签提升到它的父级(不丢结构)+ 断开任务关联。
错误一律抛 ValueError(重名/防环/空名/父级不存在),io/server.py 捕获转 400。
"""
from . import db


def _rows(conn):
    """全量标签行(id/name/parent_id)。"""
    return conn.execute("SELECT id, name, parent_id FROM tags").fetchall()


def _active_counts(conn):
    """每个标签的活跃任务数(直接关联,不含子孙)。"""
    return {r["tag_id"]: r["n"] for r in conn.execute(
        "SELECT tt.tag_id AS tag_id, COUNT(*) AS n FROM task_tags tt"
        " JOIN tasks t ON t.id = tt.task_id AND t.status = 'active'"
        " GROUP BY tt.tag_id")}


def _children_map(rows):
    """parent_id -> [row] 的邻接表。parent_id 悬空(不该发生)的归到 None。"""
    children = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r)
    return children


def _subtree_counts(rows, counts):
    """每标签的子树活跃任务总数(自己+全部子孙),筛选栏排序/显隐用。"""
    children = _children_map(rows)
    total = {}

    def _sum(r):
        if r["id"] in total:
            return total[r["id"]]
        total[r["id"]] = counts.get(r["id"], 0) + sum(
            _sum(c) for c in children.get(r["id"], []))
        return total[r["id"]]

    for r in rows:
        _sum(r)
    return total


def flat(conn):
    """平铺 [{name, parent}],供筛选栏建树。parent 为父标签名,根为 None。

    只含有活跃任务(自己或任一子孙)的标签;按子树活跃数降序,同数按名字。
    """
    rows = _rows(conn)
    if not rows:
        return []
    by_id = {r["id"]: r for r in rows}
    subtree = _subtree_counts(rows, _active_counts(conn))
    out = [
        {"name": r["name"],
         "parent": by_id[r["parent_id"]]["name"] if r["parent_id"] in by_id else None,
         "_n": subtree.get(r["id"], 0)}
        for r in rows if subtree.get(r["id"], 0) > 0
    ]
    out.sort(key=lambda t: (-t["_n"], t["name"]))
    for t in out:
        del t["_n"]
    return out


def tree(conn):
    """完整标签树(含无活跃任务的),供管理页。[{id, name, count, children}]。

    count = 直接活跃任务数;排序:子树活跃数降序,同数按名字(与筛选栏一致)。
    """
    rows = _rows(conn)
    counts = _active_counts(conn)
    subtree = _subtree_counts(rows, counts)
    children = _children_map(rows)

    def _node(r):
        kids = sorted(children.get(r["id"], []),
                      key=lambda c: (-subtree.get(c["id"], 0), c["name"]))
        return {"id": r["id"], "name": r["name"], "parent_id": r["parent_id"],
                "count": counts.get(r["id"], 0),
                "children": [_node(c) for c in kids]}

    roots = sorted(children.get(None, []),
                   key=lambda r: (-subtree.get(r["id"], 0), r["name"]))
    return [_node(r) for r in roots]


def descendants(conn, tag_id):
    """tag_id 的全部子孙 id 集合(不含自己)。Python 递归,标签少无所谓性能。"""
    children = _children_map(_rows(conn))
    seen, stack = set(), list(children.get(tag_id, []))
    while stack:
        r = stack.pop()
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        stack.extend(children.get(r["id"], []))
    return seen


def _get(conn, tag_id):
    return conn.execute("SELECT id, name, parent_id FROM tags WHERE id=?",
                        (tag_id,)).fetchone()


def _require(conn, tag_id):
    row = _get(conn, tag_id)
    if row is None:
        raise LookupError(f"标签不存在: {tag_id}")
    return row


def _check_name(conn, name, exclude_id=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("标签名不能为空")
    row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
    if row and row["id"] != exclude_id:
        raise ValueError(f"标签已存在: {name}")
    return name


def create(conn, name, parent_id=None):
    """建标签,返回 id。重名/空名/父级不存在报 ValueError。"""
    name = _check_name(conn, name)
    if parent_id is not None:
        _require(conn, parent_id)
    with conn:
        cur = conn.execute("INSERT INTO tags (name, parent_id) VALUES (?,?)",
                           (name, parent_id))
    return cur.lastrowid


def rename(conn, tag_id, name):
    """改名。不存在 LookupError;重名/空名 ValueError。"""
    _require(conn, tag_id)
    name = _check_name(conn, name, exclude_id=tag_id)
    with conn:
        conn.execute("UPDATE tags SET name=? WHERE id=?", (name, tag_id))


def set_parent(conn, tag_id, parent_id):
    """移父(parent_id=None 回根级)。防环:新父级不能是自己或自己的子孙。"""
    _require(conn, tag_id)
    if parent_id is not None:
        _require(conn, parent_id)
        if parent_id == tag_id or parent_id in descendants(conn, tag_id):
            raise ValueError("不能移到自己的子孙下(会形成环)")
    with conn:
        conn.execute("UPDATE tags SET parent_id=? WHERE id=?", (parent_id, tag_id))


def delete(conn, tag_id):
    """删标签:子标签提升到它的父级 + 断开任务关联 + 删行。不存在 LookupError。"""
    row = _require(conn, tag_id)
    with conn:
        conn.execute("UPDATE tags SET parent_id=? WHERE parent_id=?",
                     (row["parent_id"], tag_id))
        conn.execute("DELETE FROM task_tags WHERE tag_id=?", (tag_id,))
        conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
