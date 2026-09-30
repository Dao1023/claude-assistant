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
  created     INTEGER NOT NULL,          -- 创建时间,Unix 秒
  snooze_until INTEGER                   -- 推迟到此时间(Unix 秒),NULL=未推迟
);
```

> **时间字段一律 Unix 秒级整数**(v0.5.0 起;旧字符串库用 `scripts/migrate_unix_time.py` 迁移)。
> `snooze_until` 为 v0.7.0 新增(旧库用 `scripts/migrate_snooze.py` 加列)。
> 前后端边界仍传字符串,由 `core/timeutil.py` 在出入口互转。

### 2. `schedule` —— 时间驱动表(与 tasks 一对一)

start / end 的时间逻辑不同,**字段级拆分**,各填各的:

```sql
CREATE TABLE schedule (
  task_id             TEXT PRIMARY KEY REFERENCES tasks(id),
  deadline            INTEGER,   -- end 驱动:截止时间,Unix 秒
  anchor              INTEGER,   -- start 驱动:上次完成时间,Unix 秒(做完重置;新任务=now)
  expected_duration   INTEGER,   -- start 驱动:预期间隔(重要性归一化分母),秒
  recurrence_interval INTEGER    -- end 驱动:重复间隔,秒;NULL=非周期
);
```

> - **start**:`anchor` + `expected_duration` + `tasks.is_cyclic`(独立,不随 expected_duration 自动开)。
>   重要性 `log((now-anchor)/expected_duration)`。
> - **end**:`deadline` + `recurrence_interval`(空=非周期,不用 is_cyclic)。
>   过了 deadline 即 closed(超时即结束);周期任务超时 closed 当前 + 克隆下一个(deadline 顺延 interval)。
> - 间隔字段都存**秒**,与 now/anchor/deadline 同单位,公式无量纲不用换算。
> - (v0.6.0 起;旧库 `cycle_days` 用 `scripts/migrate_split_fields.py` 按 drive 拆分转秒。)

### 3. `tags` —— 标签表

```sql
CREATE TABLE tags (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  name  TEXT NOT NULL UNIQUE,           -- genshin / 家人 / 公司 / 健康 …
  parent_id INTEGER REFERENCES tags(id) -- 父标签,NULL=根;层级读写见 core/tags.py
);
```

> **层级(v0.9.0 起)**:标签为任意深度单父树(如 工作→科研→论文)。旧库用 `db._migrate` 幂等补列,
> 现有标签全成根节点。语义:隐式继承(任务挂「科研」,筛选「工作」命中);删除=子标签提升到父级+任务断关联。
> 标签总量小,子孙展开在 Python 递归(core/tags.py),不用递归 SQL。

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
  pushed_at  INTEGER NOT NULL,     -- 什么时候推的,Unix 秒
  stage      TEXT,                 -- gentle / escalating / crisis
  response   TEXT                  -- seen / clicked / ignored / done(本次响应)
);
```

> 任务的"当前推送状态"(被推几次、当前档位)由 push_log **算出**,不冗余存储,保证数据只有一份。

### 6. `settings` —— 通知规则配置(键值)

```sql
CREATE TABLE settings (
  key   TEXT PRIMARY KEY,        -- 规则键:cooldown_ratio / escalate_nags / ...
  value TEXT NOT NULL            -- 数值,存文本,读出时按类型转 int/float
);
```

> 推送的数值阈值(冷却系数/兜底冷却/升级档次数/危机阈值/轮询间隔/一次最多弹卡/夜间免打扰恢复点)
> 存这里,由 `core/settings.py` 统一读写(带进程内缓存)。**规则页展示值 = 推送代码
> 运行值,同源**。算法/逻辑(重要性公式、档位判定)不存表,保持只读。
> **临时免打扰 `dnd_until` 也存此表,但它是运行时状态不是规则**——不进 SETTINGS
> 列表(不在规则页渲染成配置行),由 `settings.get/set_dnd_until` 单独读写,到期自动失效。

## 二、操作接口(Claude Code / 前端 → APP)

任务的增删改查走 **HTTP 接口**(`io/server.py`,FastAPI),底层统一复用 `core/actions.py` 的业务逻辑。早期曾用 `commands.json` 文件信箱传话,有了 HTTP 接口后已删除——现在是同步实时调用,不再异步轮询。

接口文档由 FastAPI 自动生成:`/docs`(Swagger UI)与 `/openapi.json`,AI 可直接拉取了解全部端点。

| 方法 + 路径 | 复用 | 说明 |
|---|---|---|
| `POST /api/tasks` | `do_add` | 新增任务。start 传 expected_days/is_cyclic,end 传 recurrence_days(天,转秒存) |
| `PUT /api/tasks/{id}` | `do_update` | 改 title/note/priority/deadline/anchor/expected_days/recurrence_days/is_cyclic |
| `POST /api/tasks/{id}/done` | `do_done` | 完成。周期任务自动克隆下一个 |
| `POST /api/tasks/{id}/close` | `do_close` | 彻底关闭(不再催) |
| `POST /api/tasks/{id}/snooze` | `do_snooze` | 推迟。可带 `until`(到点,缺省 1h) |
| `GET /api/snooze-options` | `snooze_options` | 推迟预设(1h/3h/明天/下周) |
| `GET /api/tasks` | — | 面板数据(starts/ends/tags;tags 为 `[{name, parent}]` 平铺,筛选栏据此建树) |
| `GET /api/tasks/{id}` | — | 单任务详情(404 若不存在) |
| `GET /api/tasks/{id}/pushes` | — | 提醒记录(倒序) |
| `GET /api/tags` | `tags.tree` | 完整标签树(id/name/count/children),管理页 |
| `POST /api/tags` | `tags.create` | 建标签(name, parent_id?);重名/空名/父级不存在 400 |
| `PUT /api/tags/{id}` | `tags.rename/set_parent` | 改名/移父(parent_id 传 null=回根级);防环 400 |
| `DELETE /api/tags/{id}` | `tags.delete` | 删(子标签提升+任务断关联) |
| `GET /api/settings` | `settings.all` | 全部通知规则(可编辑项当前值+元信息 + 只读算法说明) |
| `PUT /api/settings` | `settings.set` | 更新一个/多个可编辑规则;未知 key / 越界 400 |
| `GET /api/funnel` | `pusher.pick` | 通知漏斗实时统计:每层筛掉了哪些任务(只算不弹);含 `dnd` 总闸当前状态 |
| `PUT /api/dnd` | `settings.set_dnd_until` | 开临时免打扰:传 `until`('YYYY-MM-DD HH:MM' 到期时刻) |
| `DELETE /api/dnd` | `settings.set_dnd_until(None)` | 立即恢复:清掉临时免打扰 |

### 各动作的语义(与通道无关)

| 动作 | APP 行为 |
|---|---|
| `add` | 插入 tasks + schedule + task_tags。start 填 anchor+expected_duration,end 填 deadline+recurrence_interval |
| `done` | status→done(真完成)。周期任务克隆下一个:start 重置 anchor,end 顺延 deadline |
| `update` | 改字段(标题/优先级/anchor/deadline/expected_duration/recurrence_interval/is_cyclic/tag 等)。延期=改 deadline |
| `close` | 手动关闭(status→closed,周期任务不再克隆) |
| **超时** | end 过 deadline 自动 closed(引擎/推送入口先跑 `close_overdue`);周期任务同时克隆下一个 |
| `snooze` | 静音(push_log 记一条,冷却期内引擎不催它) |
| `query` | 按条件查(tag/驱动/重要性 Top N) |

> **生命周期三状态**:`active`(唯一会被催)/ `done`(真完成)/ `closed`(手动关闭或超时结束)。
> done 与 closed 行为一致,保留两个是为统计成功率(done/(done+closed))。

## 三、关键查询(引擎高频用)

**1. 今日 end 清单(按结束时间排序)**
```sql
SELECT t.*, s.deadline FROM tasks t
JOIN schedule s ON s.task_id = t.id
WHERE t.drive='end' AND t.status='active'
ORDER BY s.deadline ASC;
```

**2. start 清单(SQL 只取数,重要性在 Python 算)**

重要性公式放在 Python(engine)里算,不压进数据库——以后调底数、加权重、处理边界都不用改 SQL。SQL 只负责取 anchor / expected_duration(均秒):

```sql
SELECT t.*, s.anchor, s.expected_duration
FROM tasks t
JOIN schedule s ON s.task_id = t.id
WHERE t.drive='start' AND t.status='active';
```

Python 侧对每个任务算 `importance = log((now - anchor) / expected_duration)` 后排序(全部秒级,无量纲):

```python
import math

def start_importance(anchor, expected_duration, now):
    if anchor is None or not expected_duration or expected_duration <= 0:
        return 0.0
    x = (now - anchor) / expected_duration
    if x <= 0:
        x = 1e-4               # 刚做/刚建:有限负值,排最后但不崩 JSON(不用 -inf)
    return math.log(x)          # x<1 自然得负,x=1 得 0,x>1 缓慢上升
```

> **边界**:`x <= 0` 钳到 `1e-4` 给有限负数,而不是 `-inf`——`-inf` 无法 JSON 序列化(曾致面板 500),且按秒算后 `x` 几乎不恒为 0。
> **end 的重要性**:`-log(剩余天数)`。过期任务**不会**到这里——它们在引擎/推送入口已被 `close_overdue` 置为 closed(超时即结束),无需 OVERDUE 哨兵。

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

## 四、模块落位(V4.2 说明)

V2 的 core/io/app 分层与 REST 服务面已随架构翻转退役(git 历史可查)。当前规划:

- **表结构与动作语义(上表)全部存活**——它们是"档案"的规范,与外壳无关
- 读写外壳 = dsh-task-brain 插件(会话内原生工具,execute 接 SQLite + actions 校验),规划见 [community-survey.md](community-survey.md) 阶段 3
- 写入路径继续过 `core/actions.py` 的业务校验(AI 不裸写库的原则从 V2 继承)
- `/docs` Swagger 等旧 REST 面板接口随旧服务退役;前端面板 V4.2 起不再维护

