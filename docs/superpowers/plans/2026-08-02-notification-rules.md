# 通知层重构实现计划:V1 清除 + 规则可配置

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底删除 V1 通知通道(inbox/watcher/Toast),把通知规则的数值阈值收敛为 SQLite 可配置项,并新增"通知规则"页完整展示与编辑。

**Architecture:** 单一推送通道 pusher → popup 小卡;规则数值存 SQLite `settings` 表,经 `core/settings.py` 单一模块读写(带缓存),规则页展示与代码运行同源。前端 App.vue 加顶部 Tab 切换"任务看板 / 通知规则"。

**Tech Stack:** Python 3.11 / FastAPI / SQLite / pytest(后端);Vue3 + Element Plus + Vite(前端,unplugin 自动导入 ElMessage 等)。

**Branch:** `feat-notification-rules`(已建,按需提交)

---

## 文件结构

**后端:**
- Create: `assistant/core/settings.py` — 规则单一读写口(get/set/all + 元信息 + 缓存)
- Modify: `assistant/core/db.py` — SCHEMA 加 `settings` 表 + `get_setting/set_setting/all_settings`
- Modify: `assistant/io/pusher.py` — 5 个硬编码常量改读 settings
- Modify: `assistant/io/server.py` — 加 `GET/PUT /api/settings`
- Modify: `assistant/config.py` — 删 `INBOX`
- Modify: `main.py` — 摘 V1 接线,tick 收敛;poll_interval 动态读
- Modify: `assistant/app/tray.py` — 去「立即检查」,不再 import scheduler 回调
- Modify: `pyproject.toml` — 删 watchdog、windows-toasts 依赖
- Delete: `assistant/io/notifier.py`、`assistant/io/watcher.py`、`assistant/core/inbox.py`、`assistant/app/scheduler.py`
- Delete(data): `data/inbox.json`(先备份 `.bak`)

**前端:**
- Create: `frontend/src/components/RulesPage.vue` — 规则页(只读展示 + 可编辑表单)
- Modify: `frontend/src/types/index.ts` — 加 Setting/RulesResponse 类型
- Modify: `frontend/src/api/client.ts` — 加 fetchRules/updateSettings
- Modify: `frontend/src/App.vue` — 顶部 Tab 切换看板/规则

**测试:**
- Create: `tests/core/test_settings.py`
- Modify: `tests/io/test_pusher.py`(冷却兜底测试随 settings 化微调)
- Create: `tests/io/test_server_settings.py`

---

## 设置模型(单一数据源,前后端 + 测试共用)

`core/settings.py` 定义有序 `SETTINGS` 列表,每项:`(key, default, value_type, unit, label, desc, min, max)`。
`value_type ∈ {"float","int"}`。这是唯一事实来源:`all()` 渲染规则页可编辑区,`validate()` 校验 PUT,测试断言默认值。

| key | default | type | min | max | label |
|---|---|---|---|---|---|
| `cooldown_ratio` | 0.25 | float | 0.05 | 1.0 | 冷却系数 |
| `cooldown_fallback` | 3600 | int | 60 | 86400 | 兜底冷却(秒) |
| `escalate_nags` | 3 | int | 1 | 20 | 升级档次数 |
| `crisis_importance` | 1.0 | float | 0.0 | 5.0 | 危机重要性阈值 |
| `poll_interval` | 30 | int | 5 | 600 | 轮询间隔(秒) |
| `max_concurrent` | 1 | int | 1 | 5 | 一次最多弹卡数 |

---

### Task 1: settings 存储层 + core/settings.py

**Files:**
- Modify: `assistant/core/db.py`(SCHEMA + 3 个函数)
- Create: `assistant/core/settings.py`
- Test: `tests/core/test_settings.py`

- [ ] **Step 1: db.py 加 settings 表与读写函数**

在 `SCHEMA` 末尾追加表(放在 `push_log` 之后):

```sql
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

在 db.py 末尾(`push_stats` 之后)加:

```python
# ---------- settings ----------

def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn, key, value):
    with conn:
        conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def all_settings(conn):
    return {r["key"]: r["value"]
            for r in conn.execute("SELECT key,value FROM settings").fetchall()}
```

- [ ] **Step 2: 写失败测试 `tests/core/test_settings.py`**

```python
"""测试:通知规则设置(core/settings)。用临时 DB。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, settings


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)   # 隔离缓存
    db.init_db()
    c = db.connect()
    yield c
    c.close()
    monkeypatch.setattr(settings, "_cache", None)


def test_defaults_when_table_empty(conn):
    # 表里没存过 → 返回默认值
    assert settings.get("cooldown_ratio") == 0.25
    assert settings.get("escalate_nags") == 3
    assert settings.get("poll_interval") == 30


def test_set_then_get(conn):
    settings.set("cooldown_ratio", 0.5)
    assert settings.get("cooldown_ratio") == 0.5


def test_type_coercion(conn):
    settings.set("escalate_nags", "7")
    assert settings.get("escalate_nags") == 7          # int
    assert isinstance(settings.get("escalate_nags"), int)
    settings.set("cooldown_ratio", "0.4")
    assert isinstance(settings.get("cooldown_ratio"), float)


def test_validate_rejects_out_of_range(conn):
    with pytest.raises(ValueError):
        settings.set("cooldown_ratio", 9.9)            # 超 max
    with pytest.raises(ValueError):
        settings.set("escalate_nags", 0)               # 低于 min


def test_validate_rejects_unknown_key(conn):
    with pytest.raises(KeyError):
        settings.set("nope", 1)


def test_all_returns_editable_with_meta(conn):
    items = settings.all()
    keys = [i["key"] for i in items]
    assert "cooldown_ratio" in keys and "max_concurrent" in keys
    one = next(i for i in items if i["key"] == "cooldown_ratio")
    assert one["value"] == 0.25 and one["label"] and one["desc"]
    assert one["min"] == 0.05 and one["max"] == 1.0
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest tests/core/test_settings.py -v`
Expected: FAIL(`from assistant.core import settings` 模块不存在)

- [ ] **Step 4: 实现 `assistant/core/settings.py`**

```python
"""通知规则设置:单一读写口。

数值型阈值存 SQLite settings 表,本模块提供 get/set/all,带进程内缓存。
规则页展示值 = 推送代码运行值,同源(都走本模块),不会不一致。
SETTINGS 是唯一事实来源:渲染、校验、默认、测试都从这里取。
"""
from . import db

# (key, default, type, unit, label, desc, min, max)
SETTINGS = [
    ("cooldown_ratio", 0.25, "float", "", "冷却系数",
     "冷却时长 = 任务间隔 × 此系数。越大催得越稀。", 0.05, 1.0),
    ("cooldown_fallback", 3600, "int", "秒", "兜底冷却",
     "任务无间隔字段时的冷却时长。", 60, 86400),
    ("escalate_nags", 3, "int", "次", "升级档次数",
     "end 被推这么多次后升「催办」;start 为其 2 倍。", 1, 20),
    ("crisis_importance", 1.0, "float", "", "危机重要性阈值",
     "end 重要性到此值(约剩 9 小时)无视次数直接「紧急」。", 0.0, 5.0),
    ("poll_interval", 30, "int", "秒", "轮询间隔",
     "调度循环每隔多久检查一次该不该催。", 5, 600),
    ("max_concurrent", 1, "int", "张", "一次最多弹卡",
     "同一轮最多弹出几张催办小卡。", 1, 5),
]

_BY_KEY = {s[0]: s for s in SETTINGS}
_cache = None          # {key: 已转类型的值};None=未加载


def _coerce(key, raw):
    typ = _BY_KEY[key][2]
    return float(raw) if typ == "float" else int(float(raw))


def _load():
    """从库读全部已存值并合并默认值,填充缓存。"""
    global _cache
    conn = db.connect()
    try:
        stored = db.all_settings(conn)
    finally:
        conn.close()
    _cache = {key: _coerce(key, stored[key]) if key in stored else s[1]
              for key, s in ((s[0], s) for s in SETTINGS)}


def get(key):
    """读某规则当前值(库里有用库存,没有用默认)。"""
    if key not in _BY_KEY:
        raise KeyError(f"未知设置项: {key}")
    if _cache is None:
        _load()
    return _cache[key]


def set(key, value):
    """校验后写库并更新缓存。越界 ValueError,未知 key KeyError。"""
    if key not in _BY_KEY:
        raise KeyError(f"未知设置项: {key}")
    v = _coerce(key, value)
    lo, hi = _BY_KEY[key][6], _BY_KEY[key][7]
    if not (lo <= v <= hi):
        raise ValueError(f"{key} 需在 [{lo}, {hi}] 之间,收到 {v}")
    conn = db.connect()
    try:
        db.set_setting(conn, key, v)
    finally:
        conn.close()
    if _cache is not None:
        _cache[key] = v


def all():
    """全部可编辑项 + 元信息,供规则页渲染。有序。"""
    return [{"key": k, "value": get(k), "type": s[2], "unit": s[3],
             "label": s[4], "desc": s[5], "min": s[6], "max": s[7]}
            for s in SETTINGS for k in (s[0],)]
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest tests/core/test_settings.py -v`
Expected: PASS(6 个)

- [ ] **Step 6: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add assistant/core/db.py assistant/core/settings.py tests/core/test_settings.py
git commit -m "feat: 通知规则设置存储层(core/settings + settings 表)"
```

---

### Task 2: pusher.py 常量改读 settings

**Files:**
- Modify: `assistant/io/pusher.py`
- Test: `tests/io/test_pusher.py`

- [ ] **Step 1: 改 pusher.py 引用**

把文件头部常量定义块删除:

```python
# 删除这五行
MAX_CONCURRENT = 1
COOLDOWN_RATIO = 0.25
COOLDOWN_FALLBACK = 3600
ESCALATE_NAGS = 3
CRISIS_IMPORTANCE = 1.0
```

改为 import settings:

```python
from ..core import actions, db, engine, settings
```

逐处替换使用点:
- `_cooling_down`:`cooldown = max(int(interval * COOLDOWN_RATIO), 60)` →
  `cooldown = max(int(interval * settings.get("cooldown_ratio")), 60)`;
  `_task_interval(task) or COOLDOWN_FALLBACK` → `_task_interval(task) or settings.get("cooldown_fallback")`
- `_stage`:`engine.end_importance(...) >= CRISIS_IMPORTANCE` →
  `... >= settings.get("crisis_importance")`;`nag_count >= ESCALATE_NAGS` →
  `nag_count >= settings.get("escalate_nags")`;`nag_count >= ESCALATE_NAGS * 2` →
  `nag_count >= settings.get("escalate_nags") * 2`
- `tick_push`:循环在取到 `picked` 后 break 前,统计已选数量,达到
  `settings.get("max_concurrent")` 才停(本期 max_concurrent 默认 1,逻辑等价;
  将 `picked` 改为列表收集,`_stage` 逐个算,弹出逐个 `show_task_card`)。
  为保持本期最小改动且测试对 `n==1` 的断言仍成立,实现为:收集最多
  `max_concurrent` 个 `picked`,逐个 `log_push` + `show_task_card`,返回弹出的数量。

`tick_push` 改造后主体:

```python
def tick_push():
    """主入口:挑最多 max_concurrent 个最该催的(end 优先)→ 弹小卡并记录。"""
    conn = db.connect()
    db.init_db()
    actions.close_overdue(conn)
    ends, starts = engine.today_lists(conn)
    now = _now()
    limit = settings.get("max_concurrent")

    picked = []
    for task in ends + starts:
        if len(picked) >= limit:
            break
        if _is_future_period(task, now):
            continue
        nag_count, last_at = db.push_stats(conn, task["id"])
        if _cooling_down(task, last_at, now):
            continue
        picked.append((task, _stage(task, nag_count)))
    for task, stage in picked:
        db.log_push(conn, task["id"], now, stage)
    conn.close()

    for task, stage in picked:
        on_done, on_snooze, on_ai = _make_callbacks(task["id"])
        show_task_card(task, stage, on_done, on_snooze, on_ai)
        print(f"[{to_str(now)}] 弹小卡: [{stage}] {task['title']}")
    return len(picked)
```

- [ ] **Step 2: 跑现有 pusher 测试**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest tests/io/test_pusher.py -v`
Expected: PASS(默认值与旧常量一致,行为不变)

- [ ] **Step 3: 加一条"配置生效"测试**

在 `tests/io/test_pusher.py` 末尾追加:

```python
def test_cooldown_fallback_reads_settings(conn):
    # 把兜底冷却从 3600 改小到 300s,则 10 分钟前的推送不再冷却
    from assistant.core import settings
    settings.set("cooldown_fallback", 300)
    t = _task("end", recurrence_interval=None)
    assert pusher._cooling_down(t, NOW - 600, now=NOW) is False
```

注意:`conn` fixture 已 monkeypatch DB_PATH,但 settings 缓存是模块级;在文件顶部
fixture 里已对 config.DB_PATH 换库。settings 缓存在首次 `get` 时按当前 DB_PATH 加载,
因此需保证本测试运行前缓存指向测试库。在 `tests/io/test_pusher.py` 的 `conn` fixture
内加 `monkeypatch.setattr(settings, "_cache", None)`(顶部 import settings)。

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest tests/io/test_pusher.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add assistant/io/pusher.py tests/io/test_pusher.py
git commit -m "refactor: pusher 常量改读 settings(max_concurrent 支持多卡)"
```

---

### Task 3: 后端 GET/PUT /api/settings

**Files:**
- Modify: `assistant/io/server.py`
- Test: `tests/io/test_server_settings.py`

- [ ] **Step 1: server.py 加路由**

顶部 import 加 `from ..core import settings as settings_mod`。

在 `api_unsnooze` 之后、`_mount_static(app)` 之前加:

```python
    # ---------- 通知规则设置 ----------

    @app.get("/api/settings")
    def api_get_settings():
        """全部通知规则:可编辑项(当前值+元信息) + 只读算法说明。"""
        return {"editable": settings_mod.all(), "readonly": READONLY_RULES}

    @app.put("/api/settings")
    def api_put_settings(body: dict):
        """更新一个/多个可编辑规则。未知 key 400,越界 400。"""
        errors = {}
        for k, v in body.items():
            try:
                settings_mod.set(k, v)
            except KeyError:
                errors[k] = "未知规则项"
            except ValueError as e:
                errors[k] = str(e)
        if errors:
            raise HTTPException(status_code=400, detail=errors)
        return {"editable": settings_mod.all()}
```

模块级(文件底部 `_days_to_secs` 附近)加只读规则常量:

```python
READONLY_RULES = [
    {"title": "重要性引擎",
     "desc": "start:log(距今秒/预期间隔秒),越久越大;end:-log(剩余天数),越近越大。"},
    {"title": "档位判定",
     "desc": "默认「提醒」;end 推满升级档次数升「催办」,start 为其 2 倍;"
             "end 重要性达危机阈值无视次数直接「紧急」。"},
    {"title": "优先级",
     "desc": "end 优先于 start;未来周期 end(剩余>一个周期)今晚不催;过 deadline 的 end 即关闭。"},
    {"title": "冷却与推迟",
     "desc": "冷却 = 任务间隔 × 冷却系数;推迟(snooze)未到点优先于冷却,一律不催。"},
]
```

- [ ] **Step 2: 写测试 `tests/io/test_server_settings.py`**

```python
"""测试:设置接口 GET/PUT /api/settings。用临时 DB + TestClient。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from assistant import config
from assistant.core import db, settings
from assistant.io.server import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(settings, "_cache", None)
    db.init_db()
    yield TestClient(create_app())
    monkeypatch.setattr(settings, "_cache", None)


def test_get_returns_editable_and_readonly(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    keys = [i["key"] for i in body["editable"]]
    assert "cooldown_ratio" in keys and "poll_interval" in keys
    assert len(body["readonly"]) >= 3


def test_put_updates_value(client):
    r = client.put("/api/settings", json={"cooldown_ratio": 0.5})
    assert r.status_code == 200
    val = next(i for i in r.json()["editable"] if i["key"] == "cooldown_ratio")
    assert val["value"] == 0.5


def test_put_rejects_out_of_range(client):
    r = client.put("/api/settings", json={"escalate_nags": 999})
    assert r.status_code == 400


def test_put_rejects_unknown_key(client):
    r = client.put("/api/settings", json={"bogus": 1})
    assert r.status_code == 400
```

- [ ] **Step 3: 跑测试确认通过**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest tests/io/test_server_settings.py -v`
Expected: PASS(4 个)

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add assistant/io/server.py tests/io/test_server_settings.py
git commit -m "feat: GET/PUT /api/settings 通知规则接口"
```

---

### Task 4: 删除 V1 通道 + 收尾接线

**Files:**
- Delete: `assistant/io/notifier.py`、`assistant/io/watcher.py`、`assistant/core/inbox.py`、`assistant/app/scheduler.py`
- Modify: `main.py`、`assistant/config.py`、`assistant/app/tray.py`、`pyproject.toml`
- Delete(tests): `tests/io/test_notify.py`、`tests/io/test_toast.py`、`tests/ui/test_click.py`、`tests/ui/test_dashboard.py`(若存在且引用 V1,见 Step 3)
- Data: 备份并删 `data/inbox.json`

- [ ] **Step 1: 备份并删 inbox.json**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
cp data/inbox.json data/inbox.json.bak
rm data/inbox.json
```

- [ ] **Step 2: 删 V1 四文件**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git rm assistant/io/notifier.py assistant/io/watcher.py assistant/core/inbox.py assistant/app/scheduler.py
```

- [ ] **Step 3: 删引用 V1 的测试文件**

`tests/io/test_notify.py`、`tests/io/test_toast.py`、`tests/ui/test_click.py`、
`tests/ui/test_dashboard.py` 现以 `__pycache__` 残影出现(源文件可能已删或引 V1)。
逐一确认:凡 import `notifier`/`watcher`/`inbox`/`scheduler`(app)或 `windows_toasts`
的测试文件,`git rm`。保留与 V1 无关的 `tests/io/test_pusher.py`、`test_server.py`、
`tests/core/*`。

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
grep -rl "notifier\|watcher\|inbox\|windows_toasts\|app.scheduler\|app import scheduler" tests/ || echo "none"
# 对列出的文件 git rm
```

- [ ] **Step 4: 改 main.py**

删 import:`from assistant.app.scheduler import tick as inbox_tick`、
`from assistant.io.notifier import clear_all`、`from assistant.io.watcher import start_watcher`。
改 import:`from assistant.config import POLL_INTERVAL` → `from assistant.core import settings`。

`tick()` 收敛:

```python
def tick():
    """一轮调度:跑任务推送。加锁防重入(轮询/托盘并发)。"""
    if not _tick_lock.acquire(blocking=False):
        return
    try:
        db.init_db()
        tick_push()
    finally:
        _tick_lock.release()
```

`scheduler_loop` 动态读间隔:

```python
def scheduler_loop():
    while True:
        tick()
        time.sleep(settings.get("poll_interval"))
```

`main()` 删 watcher/clear_all 接线:

```python
def main():
    db.init_db()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    _ensure_server()
    lifecycle.register_cleanup(lambda: None)   # 预留清理口;watcher/Toast 已删
    threading.Thread(
        target=lambda: run_tray(on_open=open_panel),
        daemon=True).start()
    print("Claude Assistant 已启动(催办小卡 + 推送生命周期 + WebUI 面板)…")
    tick()
    start_ui()
```

同时删文件顶部对 `inbox_tick`/`start_watcher`/`clear_all` 的引用注释更新
(顶部 docstring 第 1 点 inbox 描述删除)。

- [ ] **Step 5: 改 config.py 删 INBOX**

```python
# 删除
INBOX = DATA / "inbox.json"
```

- [ ] **Step 6: 改 tray.py 去「立即检查」**

`run_tray(on_check, on_exit=None, on_open=None)` 签名改 `run_tray(on_exit=None, on_open=None)`;
菜单删 `pystray.MenuItem("立即检查", lambda: on_check())`;删 docstring 中 on_check 说明。
(`on_exit` 参数已无调用方传,保留形参以兼容,或一并删——统一删,`main` 不再传 on_exit。)

- [ ] **Step 7: 删依赖**

`pyproject.toml` `dependencies` 删 `watchdog==6.0.0`、`windows-toasts==1.3.1`。

- [ ] **Step 8: 全量跑测试 + 启动冒烟**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest -q`
Expected: 全 PASS,无 V1 残留 import 错误

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -c "import main; print('import ok')"`
Expected: `import ok`(不启动 mainloop,仅验证 main.py 语法/import)

- [ ] **Step 9: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add -A
git commit -m "refactor: 彻底删除 V1 通知通道(inbox/watcher/Toast),tick 收敛"
```

---

### Task 5: 前端类型 + API client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: types 追加**

```typescript
/** 一项可编辑的通知规则 */
export interface EditableSetting {
  key: string
  value: number
  type: 'float' | 'int'
  unit: string
  label: string
  desc: string
  min: number
  max: number
}

/** 一段只读规则说明 */
export interface ReadonlyRule {
  title: string
  desc: string
}

/** GET /api/settings 返回 */
export interface RulesResponse {
  editable: EditableSetting[]
  readonly: ReadonlyRule[]
}
```

- [ ] **Step 2: client.ts 追加**

```typescript
/** 拉取全部通知规则(可编辑 + 只读说明)。 */
export async function fetchRules(): Promise<RulesResponse> {
  const res = await fetch('/api/settings', { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`请求失败:${res.status} ${res.statusText}`)
  }
  return (await res.json()) as RulesResponse
}

/** 更新通知规则。values 为 { key: value };400 时抛后端 detail。 */
export async function updateSettings(values: Record<string, number>): Promise<EditableSetting[]> {
  const res = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ? JSON.stringify(detail.detail) : `保存失败:${res.status}`)
  }
  const body = (await res.json()) as { editable: EditableSetting[] }
  return body.editable
}
```

import 行加 `RulesResponse, EditableSetting`。

- [ ] **Step 3: 类型检查**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant/frontend && pnpm exec vue-tsc --noEmit`
Expected: 无 TS 错误

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: 前端规则类型与 settings API client"
```

---

### Task 6: 前端 RulesPage.vue + App.vue Tab

**Files:**
- Create: `frontend/src/components/RulesPage.vue`
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 建 RulesPage.vue**

```vue
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchRules, updateSettings } from '@/api/client'
import type { EditableSetting, ReadonlyRule } from '@/types'

const editable = ref<EditableSetting[]>([])
const readonlyRules = ref<ReadonlyRule[]>([])
const loading = ref(false)
const saving = ref(false)
// 表单草稿:key -> 字符串输入值
const draft = reactive<Record<string, string>>({})

async function load() {
  loading.value = true
  try {
    const data = await fetchRules()
    editable.value = data.editable
    readonlyRules.value = data.readonly
    for (const s of data.editable) draft[s.key] = String(s.value)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载规则失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, number> = {}
    for (const s of editable.value) {
      const num = Number(draft[s.key])
      if (Number.isNaN(num)) {
        ElMessage.error(`「${s.label}」不是有效数字`)
        saving.value = false
        return
      }
      payload[s.key] = num
    }
    editable.value = await updateSettings(payload)
    ElMessage.success('已保存,下一轮调度生效')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="rules-page" v-loading="loading">
    <!-- 只读:全部规则说明 -->
    <section class="rules-readonly">
      <h2 class="section-title">通知规则(算法 · 只读)</h2>
      <div class="rule-cards">
        <el-card v-for="r in readonlyRules" :key="r.title" shadow="never" class="rule-card">
          <template #header><span class="rule-title">{{ r.title }}</span></template>
          <p class="rule-desc">{{ r.desc }}</p>
        </el-card>
      </div>
    </section>

    <!-- 可编辑:数值阈值 -->
    <section class="rules-editable">
      <h2 class="section-title">可配置项</h2>
      <el-form label-width="140px" class="settings-form">
        <el-form-item v-for="s in editable" :key="s.key" :label="s.label">
          <div class="setting-row">
            <el-input-number
              v-model="draft[s.key]"
              :min="s.min"
              :max="s.max"
              :step="s.type === 'float' ? 0.05 : 1"
              controls-position="right"
              class="setting-input"
            />
            <span class="setting-unit">{{ s.unit }}</span>
            <span class="setting-desc">{{ s.desc }}(范围 {{ s.min }} ~ {{ s.max }})</span>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
          <el-button @click="load">还原</el-button>
        </el-form-item>
      </el-form>
    </section>
  </div>
</template>

<style scoped>
.rules-page { padding: 16px 20px; overflow: auto; }
.section-title { margin: 8px 0 12px; font-size: 15px; font-weight: 700; color: #2c3e50; }
.rule-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-bottom: 20px; }
.rule-title { font-weight: 600; color: #2c3e50; }
.rule-desc { margin: 0; font-size: 13px; color: #5a6b7b; line-height: 1.6; }
.setting-row { display: flex; align-items: center; gap: 8px; }
.setting-input { width: 140px; }
.setting-unit { color: #909399; font-size: 13px; }
.setting-desc { color: #909399; font-size: 12px; }
</style>
```

注:`el-input-number` 的 v-model 需 number;`draft` 是 string。改为用计算桥接或
直接 `:model-value="Number(draft[s.key])"` + `@update:model-value="v => draft[s.key]=String(v)"`。
简化:`draft` 存 number(`Record<string, number>`),`save` 时直接用,`Number.isNaN`
判断保留。`el-input-number` 直接 `v-model="draft[s.key]"`。

- [ ] **Step 2: App.vue 加 Tab**

script 顶部加:

```typescript
import RulesPage from '@/components/RulesPage.vue'
const activeTab = ref<'board' | 'rules'>('board')
```

template:把现有 `<header>` + `<main>` 包进 `<div v-show="activeTab==='board'">`,
同级加 `<RulesPage v-show="activeTab==='rules'" />`;最顶部加 Tab 条:

```html
<el-tabs v-model="activeTab" class="page-tabs">
  <el-tab-pane label="任务看板" name="board" />
  <el-tab-pane label="通知规则" name="rules" />
</el-tabs>
```

`el-tabs` v-model 绑定 name;`activeTab` 类型对齐 string。DetailDrawer/TaskForm 保持在
看板容器内。`<style scoped>` 加:

```css
.page-tabs { padding: 8px 20px 0; background: #fff; }
.page-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
```

- [ ] **Step 3: 构建验证**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant/frontend && pnpm build`
Expected: 构建成功无 TS/Vite 错误

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add frontend/src/components/RulesPage.vue frontend/src/App.vue
git commit -m "feat: 通知规则页 + 顶部 Tab 切换"
```

---

### Task 7: 端到端验证 + 文档

**Files:**
- Modify: `docs/architecture.md`、`docs/task-system.md`(去 V1 描述,补 settings)

- [ ] **Step 1: 后端全量测试**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant && .venv/Scripts/python -m pytest -q`
Expected: 全 PASS

- [ ] **Step 2: 前端构建**

Run: `cd C:/Users/Dao/Code/dao1023/claude-assistant/frontend && pnpm build`
Expected: 成功

- [ ] **Step 3: 启动冒烟(人工)**
启动程序 → 托盘点「打开面板」→ 顶部出现「任务看板 | 通知规则」Tab;
切到通知规则 → 看到只读规则 + 六个可编辑项;改冷却系数保存 → 提示成功;
托盘只余「打开面板 / 退出」。

- [ ] **Step 4: 更新文档**
`docs/architecture.md`/`docs/task-system.md` 删除 inbox/watcher/Toast 相关段落,
补 settings 表与 `/api/settings` 说明。

- [ ] **Step 5: Commit**

```bash
cd C:/Users/Dao/Code/dao1023/claude-assistant
git add docs/
git commit -m "docs: 架构文档去 V1、补通知规则设置"
```

---

## Self-Review 记录

- **Spec 覆盖:** 删除 V1(Task 4)、规则可配置存储(1)/接口(3)/前端(5,6)、
  pusher 常量化(2)、文档与验收(7)。无遗漏。
- **类型一致:** `settings.get/set/all`、`db.get_setting/set_setting/all_settings`、
  `EditableSetting/RulesResponse` 在前后端命名一致;`activeTab` 前后一致。
- **Placeholder:** 各步含完整代码与命令,无 TBD/TODO。
- **max_concurrent:** 默认 1,`tick_push` 返回弹出数,旧测试 `n==1`/`n==0` 断言仍成立。
