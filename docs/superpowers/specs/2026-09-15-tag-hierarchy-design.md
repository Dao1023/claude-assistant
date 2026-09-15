# 标签分级筛选 设计文档

> 2026-09-15。目标:标签从同级平铺升级为**任意深度树 + 隐式继承筛选**,解决"标签一多筛选麻烦"的问题。
> 本阶段只做分级筛选;按 tag 分类的卡片型展示界面留待分级落地后另开设计。

## 已确认的决策

| 决策点 | 结论 |
|---|---|
| 范围 | 只做分级筛选,卡片展示下轮再做 |
| 层级 | 任意深度树,单父级 |
| 筛选语义 | 隐式继承:任务挂「科研」,筛选「工作」自动命中 |
| 管理入口 | 独立「标签管理」Tab |
| 筛选栏形态 | 分级 chips(父 chip + 展开箭头,子 chips 缩进下一行) |
| 管理页形态 | 选中行 + 顶部工具栏 + **拖拽调整层次** |

默认约定(未单列,实现遵守):多标签筛选仍是"或"关系;父标签只有在某子孙下有活跃任务时才出现在筛选栏;`GET /api/tasks` 的 tags 升级后旧前端不兼容(前后端同发,无兼容负担);AI 的 query 通道不动。

## 数据模型

`tags` 表加一列(邻接表,方案 A):

```sql
parent_id INTEGER REFERENCES tags(id)   -- NULL = 根标签
```

- 迁移:沿用 `db._migrate` 幂等模式(PRAGMA table_info 判缺补列),老库启动自动升级,现有标签全成根节点。
- 查子孙不上递归 SQL:标签总量几十,读全表在 Python 递展开。

## 后端

新建 `core/tags.py`(标签树读取与维护,与任务逻辑解耦):

| 函数 | 行为 |
|---|---|
| `tree(conn)` | 标签树 `[{id, name, count, children}]`,count=活跃任务数 |
| `flat(conn)` | 平铺 `[{name, parent}]`(parent 为父名或 None),供筛选栏建树 |
| `descendants(conn, tag_id)` | 子孙 id 集合(Python 递归) |
| `create(conn, name, parent_id=None)` | 建标签;重名报错 |
| `rename(conn, tag_id, name)` | 改名;重名报错 |
| `set_parent(conn, tag_id, parent_id)` | 移父;防环(新父级不能是自己或自己的子孙) |
| `delete(conn, tag_id)` | 子标签提升到它的父级 + 断任务关联 + 删行 |

错误一律抛 `ValueError`,`io/server.py` 捕获转 400(中文 detail);标签不存在 404。

API:

- `GET /api/tasks` 的 `tags` 字段:`string[]` → `{name, parent}[]`
- `GET /api/tags` → `{tree: [...]}`(管理页)
- `POST /api/tags` `{name, parent_id?}` → 201
- `PUT /api/tags/{id}` `{name?, parent_id?}`(parent_id 传 null = 移回根级)
- `DELETE /api/tags/{id}`

筛选仍在**前端**做:`matchTags` 把选中标签展开成"它+全部子孙"集合再或匹配,后端 dashboard 数据不变。

## 前端

1. **TagFilter 改造**:由 `{name,parent}[]` 建树;父 chip 带展开箭头;勾选父=整个子树(子 chips 跟随选中,部分选中显示半态样式);多选"或"关系不变;顶部栏保持横向紧凑。
2. **TaskForm 标签选择**:下拉选项按层级缩进(前缀 `└`/`·` 缩进),保留 allow-create,新标签建成根节点。
3. **TagsPage(新 Tab)**:树形列表(名字 + 活跃任务数),点选行,顶部工具栏:新建 / 改名 / 移动 / 删除(确认框,说明子标签提升+任务断关联);**HTML5 拖拽**:拖到某行上=成为其子标签,拖到顶部"根级区"=移回根级,非法落点(自己/子孙)禁放。

## 错误处理

- 防环:后端 400(前端拖拽先禁放,双保险)
- 重名:400
- 删除:前端确认框 → 子标签提升到父级 + 任务断关联
- 迁移失败不影响原有功能(纯加列)

## 测试

- `tests/core/test_tags.py`:树构建、子孙展开、防环、删除提升、重名
- `tests/io/` API 层:四个新端点正常 + 400/404 分支
- 前端无单测(与现状一致),真机联调由王导过一遍清单
