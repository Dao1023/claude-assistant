# 通知层重构设计:V1 清除 + 规则可配置

日期:2026-08-02
分支:feat-notification-rules

## 背景与目标

claude-assistant 现有两套并行通知通道:V1(inbox.json + watcher + 系统 Toast)与
V2(SQLite 任务 + pusher + tkinter 小卡)。V1 已无生产者(762 条历史全是 pusher
早期写入的残留),只进不出,却每轮空扫,是"通知频繁/干扰"与技术债的来源。

本次目标:

1. **彻底删除 V1 通道**(代码 + inbox.json 数据),只留 V2 作为唯一推送通道。
2. **通知规则可显示、可配置**:新增"通知规则"页,完整展示全部规则,数值型阈值
   可编辑、即改即生效。
3. **系统干净、数据流单一、代码高效不冗杂**。

与本次正交的上次未提交修复(托盘退出带走整程序 + explorer 重启托盘重建,
`lifecycle.py` 等)原样保留,仅随 V1 删除调整其清理项。

## 一、V1 清除

### 删除的文件(整文件)

- `assistant/io/notifier.py` — 系统 Toast 弹窗
- `assistant/io/watcher.py` — watchdog 监听 inbox.json
- `assistant/core/inbox.py` — 信箱读写
- `assistant/app/scheduler.py` — inbox_tick(V1 调度)

### 删除的数据

- `data/inbox.json`:先备份为 `data/inbox.json.bak`(不进 git),再删除原文件。

### 摘除的接线 / 引用

- `main.py`:移除 `inbox_tick`、`start_watcher`、`clear_all`、`observer` 相关;
  `tick()` 收敛为只跑 `tick_push()`。
- `assistant/config.py`:移除 `INBOX` 常量。
- 依赖 `windows_toasts`:确认 popup 小卡为唯一出口后从依赖移除。

### 连锁简化(系统更干净)

- watcher 删除 → 调度只剩"定时轮询"一条路,不再有"文件变更触发"支线;
  `main()` 不再需要 `observer.stop()` 清理。
- 系统 Toast 删除 → `clear_all()`(清 Toast 队列)无存在意义,
  `lifecycle.register_cleanup` 的清理项对应减少。
- 托盘菜单去掉「立即检查」(冷却期点了无反馈,体验是"谜"),只留
  「打开面板 / 退出」。调度全自动,不依赖手动。
- `_tick_lock` 保留(watcher 没了,但 scheduler_loop 与托盘的并发面仍在),
  触发面更干净。

## 二、通知规则可配置

### 可编辑项(数值型阈值)

| key | 默认值 | 含义 |
|---|---|---|
| `cooldown_ratio` | 0.25 | 冷却 = 任务间隔 × 此系数 |
| `cooldown_fallback` | 3600 | 无间隔任务的兜底冷却(秒) |
| `escalate_nags` | 3 | end 被推几次升「催办」;start 为 2 倍 |
| `crisis_importance` | 1.0 | end 重要性到此值(约剩 9h)升「紧急」 |
| `poll_interval` | 30 | 调度轮询间隔(秒) |
| `max_concurrent` | 1 | 一次最多弹几张卡 |

### 只读展示项(算法/逻辑,不开放编辑,避免配坏引擎)

- 重要性公式:start `log(距今/预期间隔)`、end `-log(剩余天数)`
- 档位判定:gentle → escalating → crisis 完整逻辑
- 优先级:end 优先于 start、未来周期 end 今晚不催、过期即关闭
- snooze 机制:推迟优先于冷却

### 存储与数据流(单一数据源)

- 存储:SQLite 新增 `settings` 表(key TEXT PRIMARY KEY, value TEXT)。
  与任务数据同库同生命周期,`data/` 已 gitignore,不进 git。
- 新增 `assistant/core/settings.py` 模块,提供:
  - `get(key)` → 读 settings 表(带进程内缓存,改后失效)
  - `set(key, value)` → 写表并失效缓存
  - `all()` → 返回全部可配置项当前值 + 元信息(供规则页渲染)
- 代码内所有硬编码常量(pusher/config 等)统一改为 `settings.get(...)`。
  **规则页展示值 = 代码实际运行值**,同源,不会不一致。

```
编辑 → POST /api/settings → settings 表
读取 → pusher/engine 每 tick 调 settings.get(key) → 表(缓存)
展示 → GET /api/settings → 规则页(只读项也从同源渲染)
```

### 后端接口

- `GET /api/settings` → 全部规则(可编辑项当前值 + 只读项说明),供规则页。
- `POST /api/settings` → 更新一个/多个可编辑 key;校验类型与范围;
  写库并失效缓存,下次 tick 生效。`poll_interval` 改动对调度循环即时生效
  (循环每轮重读该值)。

## 三、前端:通知规则页

- 进入方式:**顶部 Tab 切换** —「任务看板 | 通知规则」。
- 规则页布局:
  - 上半部:**全部规则只读展示**(引擎公式、档位判定、冷却算法、优先级、
    snooze),用卡片/表格讲清楚。
  - 下半部:**可编辑数值项**(输入框 + 保存),保存写 `/api/settings`,即时生效。
- 新增组件:`RulesPage.vue`(或 `SettingsPage.vue`),`App.vue` 加 Tab 状态切换
  看板 / 规则两个视图。
- `api/client.ts` 增加 `getSettings` / `updateSettings`。

## 四、非目标(YAGNI)

- 不做可视化规则编辑器(重要性公式/档位逻辑保持只读)。
- 不保留任何形式的系统 Toast / 系统通知中心弹窗。
- 不保留托盘「立即检查」。
- 不做侧边栏导航(仅两页,顶部 Tab 足够)。

## 五、验收标准

1. V1 四文件 + inbox.json 删除,`main.py`/`config.py` 无 V1 残留引用,程序正常启动。
2. 唯一推送出口为 pusher → popup 小卡;托盘点退出仍能带走整程序(lifecycle 不破坏)。
3. 规则页完整展示全部规则;六个可编辑项改值后写库、下次 tick 生效。
4. 代码中不再有通知规则的硬编码魔法数,全部经 `settings.get`。
