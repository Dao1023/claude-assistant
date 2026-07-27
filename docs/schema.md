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

## 二、指令格式(Claude Code → APP)

Claude Code 把用户自然语言翻译成指令,写到 `commands.json`,APP 监听解析后操作 SQLite,回写结果。

```json
{
  "commands": [
    {
      "id": "uuid",
      "action": "add",
      "payload": {
        "title": "每周打周本",
        "drive": "end",
        "is_cyclic": 1,
        "cycle_days": 7,
        "priority": 3,
        "tags": ["genshin"]
      },
      "status": "pending",
      "result": null
    }
  ]
}
```

- `action`: `add` / `done` / `update` / `close` / `snooze` / `query`
- `status`: APP 处理后改 `processed`,query 的答案写进 `result`。
- APP 监听 `commands.json` 变更(watchdog),逐条执行,回写。

### 各 action 的语义

| action | APP 行为 |
|---|---|
| `add` | 插入 tasks + schedule + task_tags |
| `done` | 标记完成。周期任务:克隆下一个(anchor/cycle 重置,push 计数清零);非周期:status→done |
| `update` | 改字段(标题/优先级/deadline/周期/tag 等) |
| `close` | 彻底关闭(周期任务不再克隆) |
| `snooze` | 静音到某时刻(push_log 记一条,引擎暂停催它) |
| `query` | 按条件查(tag/驱动/重要性 Top N),结果写 result |

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

## 四、落地步骤(开发顺序)

1. [ ] 建库脚本:按上述 DDL 建 5 张表(`assistant/db.py`)
2. [ ] 指令解析:监听 commands.json,实现 add/done/update/close/snooze/query(`assistant/commands.py`)
3. [ ] 重要性引擎:定时算 start/end 重要性,产出两个清单(`assistant/engine.py`)
4. [ ] 推送生命周期:接 V1 的 notifier,按三档催促 + 节流,写 push_log(`assistant/pusher.py`)
5. [ ] 周期克隆:done 时自动建下一个任务
6. [ ] 与 V1 notifier/launcher/tray 打通

> 模块将新增 `db.py / commands.py / engine.py / pusher.py`,复用现有 `notifier.py / launcher.py / tray.py / watcher.py`。
