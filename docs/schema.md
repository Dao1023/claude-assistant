# 实现方案:表结构与指令格式

> 本文是**方案层**(怎么落地)。需求见 [requirements.md](requirements.md),概念模型见 [task-system.md](task-system.md) / [lifecycle.md](lifecycle.md),选型见 [storage.md](storage.md)。
> 表结构会随开发反复调整,以本文为最新准。

## 一、SQLite 表结构

### 1. `tasks` —— 任务主表

```sql
CREATE TABLE tasks (
  id          TEXT PRIMARY KEY,          -- uuid
  title       TEXT NOT NULL,             -- 任务内容
  note        TEXT,                      -- 备注
  drive       TEXT NOT NULL,             -- 驱动方式:'start' / 'end'
  is_cyclic   INTEGER NOT NULL DEFAULT 0,-- 是否周期任务(1/0)
  priority    INTEGER NOT NULL DEFAULT 3,-- 主观优先级 1-5
  status      TEXT NOT NULL DEFAULT 'active', -- active / done / closed
  created     TEXT NOT NULL              -- 创建时间 ISO 格式
);
```

### 2. `schedule` —— 时间驱动表(与 tasks 一对一)

start / end 的时间逻辑不同,拆出来,各填各的:

```sql
CREATE TABLE schedule (
  task_id     TEXT PRIMARY KEY REFERENCES tasks(id),
  deadline    TEXT,          -- end 驱动:截止时间
  anchor      TEXT,          -- start 驱动:上次完成时间(做完重置;新任务=created)
  cycle_days  INTEGER        -- 周期天数。end 周期=原神每日1/周本7;
                             -- start 周期="正常周期"(归一化分母,如体检365/看朋友30)
);
```

> - **end + is_cyclic**:`cycle_days` 是过期后重建的间隔。
> - **start**:`cycle_days` 是"正常周期",用于重要性归一化 `log(距上次/cycle_days)`。
> - **end 非周期**:`cycle_days` 为 NULL,只填 `deadline`。

### 3. `tags` —— 标签表

```sql
CREATE TABLE tags (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name  TEXT NOT NULL UNIQUE            -- genshin / 家人 / 公司 / 健康 …
);
```

### 4. `task_tags` —— 任务-标签关联(多对多)

```sql
CREATE TABLE task_tags (
  task_id TEXT REFERENCES tasks(id),
  tag_id  INTEGER REFERENCES tags(id),
  PRIMARY KEY (task_id, tag_id)
);
```

### 5. `push_log` —— 推送流水(独立于任务,一对多)

```sql
CREATE TABLE push_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT REFERENCES tasks(id),
  pushed_at  TEXT NOT NULL,        -- 什么时候推的
  stage      TEXT,                 -- gentle / escalating / crisis
  response   TEXT                  -- seen / clicked / ignored / done(本次响应)
);
```

> 任务的"当前推送状态"(被推几次、当前档位)由 push_log **算出**,不冗余存储,保证数据只有一份。

## 二、操作接口(Claude Code / 前端 → APP)

任务的增删改查走 **HTTP 接口**(`io/server.py`,FastAPI),底层统一复用 `core/actions.py` 的业务逻辑。早期曾用 `commands.json` 文件信箱传话,有了 HTTP 接口后已删除——现在是同步实时调用,不再异步轮询。

接口文档由 FastAPI 自动生成:`/api/docs`(Swagger UI)与 `/api/openapi.json`,AI 可直接拉取了解全部端点。

| 方法 + 路径 | 复用 | 说明 |
|---|---|---|
| `POST /api/tasks` | `do_add` | 新增任务。传 `cycle_days` 即视为周期任务 |
| `PUT /api/tasks/{id}` | `do_update` | 改 title/note/priority/deadline/anchor/cycle_days |
| `POST /api/tasks/{id}/done` | `do_done` | 完成。周期任务自动克隆下一个 |
| `POST /api/tasks/{id}/close` | `do_close` | 彻底关闭(不再催) |
| `POST /api/tasks/{id}/snooze` | `do_snooze` | 稍后(push_log 记一条) |
| `GET /api/tasks` | — | 面板数据(starts/ends/tags) |
| `GET /api/tasks/{id}` | — | 单任务详情(404 若不存在) |
| `GET /api/tasks/{id}/pushes` | — | 提醒记录(倒序) |

### 各动作的语义(与通道无关)

| 动作 | APP 行为 |
|---|---|
| `add` | 插入 tasks + schedule + task_tags |
| `done` | 标记完成。周期任务:克隆下一个(anchor/cycle 重置,push 计数清零);非周期:status→done |
| `update` | 改字段(标题/优先级/deadline/周期/tag 等) |
| `close` | 彻底关闭(周期任务不再克隆) |
| `snooze` | 静音(push_log 记一条,冷却期内引擎不催它) |
| `query` | 按条件查(tag/驱动/重要性 Top N) |

## 三、关键查询(引擎高频用)

**1. 今日 end 清单(按结束时间排序)**
```sql
SELECT t.*, s.deadline FROM tasks t
JOIN schedule s ON s.task_id = t.id
WHERE t.drive='end' AND t.status='active'
ORDER BY s.deadline ASC;
```

**2. start 清单(SQL 只取数,重要性在 Python 算)**

重要性公式放在 Python(engine)里算,不压进数据库——以后调底数、加权重、处理边界都不用改 SQL。SQL 只负责取 anchor / cycle_days:

```sql
SELECT t.*, s.anchor, s.cycle_days
FROM tasks t
JOIN schedule s ON s.task_id = t.id
WHERE t.drive='start' AND t.status='active';
```

Python 侧对每个任务算 `importance = log(距今天数 / cycle_days)` 后排序:

```python
import math
from datetime import date

def start_importance(anchor: date, cycle_days: int, today: date) -> float:
    elapsed = (today - anchor).days
    if cycle_days <= 0:
        return 0.0
    x = elapsed / cycle_days
    if x <= 0:
        return float("-inf")   # 还没到周期,不排上号
    return math.log(x)          # x<1 自然得到负数,x=1 得 0,x>1 缓慢上升
```

> **边界**:`x <= 0`(当天刚做/锚点在未来)返回 -inf,排到最后;`x < 1` 时 log 为负,天然排在 `x > 1` 之后——这正是"没到周期不急"的语义,无需特判。
> **end 的重要性**同理在 Python 算:`-log(剩余天数)`,剩余 ≤ 0(已过期)返回一个很大固定值,表示"已错过,最高优先"。

**3. 某任务的推送统计(算档位)**
```sql
SELECT COUNT(*) AS nag_count, MAX(pushed_at) AS last_at
FROM push_log WHERE task_id = ?;
```

**4. 按 tag 筛/隐藏**
```sql
SELECT t.* FROM tasks t
JOIN task_tags tt ON tt.task_id = t.id
JOIN tags g ON g.id = tt.tag_id
WHERE g.name = 'genshin';   -- 或 != 'genshin' 隐藏
```

## 四、模块落位(现状)

已全部分层落地,依赖单向 `config → core → io → app → main` 无环:

- `core/db.py` — 建库 + 连接 + 基础 CRUD(5 张表)
- `core/actions.py` — 任务动作 add/done/update/close/snooze/query(纯业务,供 HTTP 与催办小卡复用)
- `core/engine.py` — 重要性引擎:start `log(距上次/周期)`、end `-log(剩余)`,产出两个清单
- `core/queries.py` — 面板数据加工(倒计时/距上次天数/log 值/tag)
- `io/server.py` — FastAPI:查询 + 写接口,托管前端构建产物
- `io/pusher.py` — 推送生命周期:三档催促 + 节流,弹催办小卡,写 push_log
- `io/notifier.py / launcher.py / watcher.py`、`app/scheduler.py / tray.py` — 沿用 V1

前端面板为独立 Vue3 工程(`frontend/`,Vite + Element Plus + Tailwind),经 `/api` 与本服务交互。

