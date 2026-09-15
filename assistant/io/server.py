"""FastAPI 面板服务:喂数据给 WebUI + 任务增删改查,并托管前端构建产物。

属于 io 层:查询走 core/queries,写操作复用 core/actions(与催办小卡同一套业务逻辑)。

查询:
- GET  /api/tasks            → {'starts','ends','tags'}(面板数据)
- GET  /api/tasks/{id}       → 单任务详情(404 若不存在)
- GET  /api/tasks/{id}/pushes → 提醒记录(倒序)

写操作(复用 core/actions):
- POST   /api/tasks           → 新增任务
- PUT    /api/tasks/{id}      → 改 title/note/priority/deadline/anchor/cycle_days
- POST   /api/tasks/{id}/done → 完成(周期任务自动克隆下一个)
- POST   /api/tasks/{id}/close → 关闭(不再催)
- POST   /api/tasks/{id}/snooze → 稍后(记 push_log)

标签(层级,见 core/tags.py):
- GET    /api/tags             → 完整标签树(管理页)
- POST   /api/tags             → 建标签(name, parent_id?)
- PUT    /api/tags/{id}        → 改名/移父(parent_id 传 null=回根级)
- DELETE /api/tags/{id}        → 删(子标签提升+任务断关联)

接口文档:FastAPI 自带 /docs(Swagger)与 /openapi.json,AI 可自查。
时间字段:前端传/收字符串,本层在出入口与内部 Unix int 互转(core/timeutil.py)。
开发模式另起 `pnpm dev`(Vite 代理 /api);生产模式由本服务托管 frontend/dist。
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import WEB_DIST
from ..core import actions, funnel, queries, tags as tags_mod
from ..core import settings as settings_mod
from ..core.timeutil import SECONDS_PER_DAY, now_ts, to_ts
from . import events


# 只读规则说明(算法/逻辑,不开放编辑),规则页展示用
READONLY_RULES = [
    {"title": "重要性引擎",
     "desc": "start:log(距今秒/预期间隔秒),越久越大;end:-log(剩余天数),越近越大。"},
    {"title": "档位判定",
     "desc": "默认「提醒」;end 推满升级档次数升「催办」,start 为其 2 倍;"
             "end 重要性达危机阈值无视次数直接「紧急」。"},
    {"title": "优先级",
     "desc": "end 优先于 start;未来周期 end(剩余>一个周期)今晚不催;过 deadline 的 end 即关闭。"},
    {"title": "推迟与节流",
     "desc": "推迟(snooze)未到点一律不催;节流=限量(每轮最多几张)+推送间隔(最快多久一轮),防推送轰炸。"},
]


# ---------- 请求体模型(Pydantic 校验 + 自动文档) ----------

class AddTaskIn(BaseModel):
    title: str
    drive: str = Field(pattern="^(start|end)$")
    deadline: Optional[str] = None              # end 驱动:'YYYY-MM-DD HH:MM'
    anchor: Optional[str] = None                # start 驱动:'YYYY-MM-DD',缺省取今天
    expected_days: Optional[float] = None       # start 驱动:预期间隔(天),转秒存
    recurrence_days: Optional[float] = None     # end 驱动:重复间隔(天),转秒存;空=非周期
    is_cyclic: int = 0                          # 仅 start:完成后是否重置
    priority: int = 3
    note: Optional[str] = None
    tags: list[str] = []


class UpdateTaskIn(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    priority: Optional[int] = None
    deadline: Optional[str] = None
    anchor: Optional[str] = None
    expected_days: Optional[float] = None
    recurrence_days: Optional[float] = None
    is_cyclic: Optional[int] = None
    tags: Optional[list[str]] = None            # 传了则覆盖式更新;空数组=清空;不传=不动


class SnoozeIn(BaseModel):
    until: Optional[str] = None        # 推迟到此时间('YYYY-MM-DD HH:MM'),缺省 1 小时
    note: Optional[str] = None         # 留言:为什么推迟


class DoneIn(BaseModel):
    note: Optional[str] = None         # 留言:完成备注


class DndIn(BaseModel):
    until: str                       # 临时免打扰到此时间('YYYY-MM-DD HH:MM')


class AiReplyIn(BaseModel):
    text: str                        # 用户在浮窗回 AI 的话


class TagIn(BaseModel):
    name: Optional[str] = None       # 改名(POST 必填,由端点校验)
    parent_id: Optional[int] = None  # 父标签;PUT 传 null = 移回根级


def create_app() -> FastAPI:
    app = FastAPI(title="Claude Assistant")

    @app.get("/api/tasks")
    def api_tasks():
        conn = queries.db.connect()
        try:
            actions.close_overdue(conn)          # 超时即关闭:过期 end 任务先落 closed
            data = queries.dashboard_data(conn)
            data["tags"] = tags_mod.flat(conn)   # [{name, parent}],筛选栏建树
            return data
        finally:
            conn.close()

    # ---------- 标签管理(层级) ----------

    @app.get("/api/tags")
    def api_tags():
        """完整标签树(含无活跃任务的),供管理页。"""
        conn = queries.db.connect()
        try:
            return {"tree": tags_mod.tree(conn)}
        finally:
            conn.close()

    @app.post("/api/tags", status_code=201)
    def api_tag_add(body: TagIn):
        if not body.name:
            raise HTTPException(status_code=400, detail="标签名不能为空")
        conn = queries.db.connect()
        try:
            try:
                tid = tags_mod.create(conn, body.name, body.parent_id)
            except LookupError:
                raise HTTPException(status_code=404, detail="父标签不存在")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"id": tid}
        finally:
            conn.close()

    @app.put("/api/tags/{tag_id}")
    def api_tag_update(tag_id: int, body: TagIn):
        conn = queries.db.connect()
        try:
            try:
                if body.name is not None:
                    tags_mod.rename(conn, tag_id, body.name)
                # exclude_unset 区分「没传」和「传了 null」:后者=移回根级
                if "parent_id" in body.model_dump(exclude_unset=True):
                    tags_mod.set_parent(conn, tag_id, body.parent_id)
            except LookupError:
                raise HTTPException(status_code=404, detail="标签不存在")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"updated": True}
        finally:
            conn.close()

    @app.delete("/api/tags/{tag_id}")
    def api_tag_delete(tag_id: int):
        """删标签:子标签提升到它的父级 + 断开任务关联。"""
        conn = queries.db.connect()
        try:
            try:
                tags_mod.delete(conn, tag_id)
            except LookupError:
                raise HTTPException(status_code=404, detail="标签不存在")
            return {"deleted": True}
        finally:
            conn.close()

    @app.get("/api/tasks/{tid}")
    def api_task_detail(tid: str):
        conn = queries.db.connect()
        try:
            detail = queries.task_detail(tid, conn)
            if detail is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            return detail
        finally:
            conn.close()

    @app.get("/api/tasks/{tid}/pushes")
    def api_task_pushes(tid: str):
        conn = queries.db.connect()
        try:
            return {"pushes": queries.task_pushes(tid, conn)}
        finally:
            conn.close()

    # ---------- 写操作(复用 core/actions) ----------

    @app.post("/api/tasks", status_code=201)
    def api_add(body: AddTaskIn):
        payload = body.model_dump()
        # 边界转换:前端传字符串/天数,内部存 Unix int / 秒
        payload["deadline"] = to_ts(payload.get("deadline"))
        payload["anchor"] = to_ts(payload.get("anchor"))
        payload["expected_duration"] = _days_to_secs(payload.pop("expected_days"))
        payload["recurrence_interval"] = _days_to_secs(payload.pop("recurrence_days"))
        conn = queries.db.connect()
        try:
            return actions.do_add(conn, payload)
        finally:
            conn.close()

    @app.put("/api/tasks/{tid}")
    def api_update(tid: str, body: UpdateTaskIn):
        _require_task(tid)
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        # 边界转换:时间字段字符串 -> Unix int;天数字段 -> 秒(仅在传了对应字段时)
        if "deadline" in payload:
            payload["deadline"] = to_ts(payload["deadline"])
        if "anchor" in payload:
            payload["anchor"] = to_ts(payload["anchor"])
        if "expected_days" in payload:
            payload["expected_duration"] = _days_to_secs(payload.pop("expected_days"))
        if "recurrence_days" in payload:
            payload["recurrence_interval"] = _days_to_secs(payload.pop("recurrence_days"))
        conn = queries.db.connect()
        try:
            return actions.do_update(conn, {"task_id": tid, **payload})
        finally:
            conn.close()

    @app.post("/api/tasks/{tid}/done")
    def api_done(tid: str, body: Optional[DoneIn] = None):
        _require_task(tid)
        note = body.note if body else None
        conn = queries.db.connect()
        try:
            result = actions.do_done(conn, {"task_id": tid})
            if not result.get("error"):
                title = _task_title(conn, tid)
                queries.db.log_push(conn, tid, now_ts(), "done",
                                    response="done", note=note)
                events.publish("done", task_id=tid, title=title, note=note)
            return result
        finally:
            conn.close()

    @app.post("/api/tasks/{tid}/close")
    def api_close(tid: str):
        _require_task(tid)
        conn = queries.db.connect()
        try:
            return actions.do_close(conn, {"task_id": tid})
        finally:
            conn.close()

    @app.post("/api/tasks/{tid}/snooze")
    def api_snooze(tid: str, body: Optional[SnoozeIn] = None):
        _require_task(tid)
        until = to_ts(body.until) if body and body.until else None
        note = body.note if body else None
        conn = queries.db.connect()
        try:
            result = actions.do_snooze(conn, {"task_id": tid, "until": until, "note": note})
            events.publish("snooze", task_id=tid, until=result.get("until"),
                           title=_task_title(conn, tid), note=note)
            return result
        finally:
            conn.close()

    @app.get("/api/snooze-options")
    def api_snooze_options(task_id: Optional[str] = None):
        """推迟选项,按任务时间尺度动态算(start=预期×系数,end=剩余×系数)。

        task_id 缺省 → 兜底 1h/3h(兼容)。任务从今日清单取(含 drive/deadline/
        expected_duration),取不到则兜底。
        """
        task = None
        if task_id:
            conn = queries.db.connect()
            try:
                from ..core import engine
                ends, starts = engine.today_lists(conn)
                for t in ends + starts:
                    if t["id"] == task_id:
                        task = t
                        break
            finally:
                conn.close()
        opts = actions.snooze_options(task)
        # until 按规范给边界字符串,前端发回后 to_ts 统一转 int。不给 int(边界一律
        # 字符串),也避开 Pydantic v2 拒 int→str 的 422。带秒(to_str 只到分,会丢
        # 几十秒精度,短档推迟 12 分钟经不起丢);to_ts 能解析 'YYYY-MM-DD HH:MM:SS'。
        from datetime import datetime
        def _s(ts):
            return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
        return {"options": [{"key": k, "label": lbl, "until": _s(ts)}
                            for k, (lbl, ts) in opts.items()]}

    @app.delete("/api/tasks/{tid}/snooze")
    def api_unsnooze(tid: str):
        """清除推迟,恢复正常催促节奏。"""
        _require_task(tid)
        conn = queries.db.connect()
        try:
            return actions.do_unsnooze(conn, {"task_id": tid})
        finally:
            conn.close()

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

    # ---------- 通知漏斗(规则页实时数据) ----------

    @app.get("/api/funnel")
    def api_funnel():
        """每层当前筛掉了哪些任务(只算不弹,无副作用)。

        复用 pusher.pick 的同一条过滤管线,保证页面看到的 = 真实推送会发生。
        返回每层:说明 + 被挡任务数 + 被挡任务列表 + 该层配置项当前值。
        """
        from . import pusher
        conn = queries.db.connect()
        try:
            actions.close_overdue(conn)      # 与真实推送同前置:过期 end 先关闭
            picked, blocked = pusher.pick(conn)
        finally:
            conn.close()

        editable = {s["key"]: s for s in settings_mod.all()}
        layers = []
        for meta in funnel.LAYERS:
            lid = meta["id"]
            hits = blocked.get(lid, [])
            layers.append({
                "id": lid,
                "label": meta["label"],
                "desc": meta["desc"],
                "blocked_count": len(hits),
                "blocked_tasks": [
                    {"id": t["id"], "title": t["title"], "reason": reason}
                    for t, reason in hits
                ],
                "settings": [editable[k] for k in meta["setting_keys"]],
            })
        # 通过所有过滤、本轮将弹出的任务(在「定档位」层展示)
        will_push = [{"id": t["id"], "title": t["title"], "stage": stage}
                     for t, stage, _ in picked]
        # 免打扰总闸当前状态(供规则页顶部卡片展示/操作)
        from ..core.timeutil import now_ts, to_str
        dnd_until = settings_mod.get_dnd_until()
        dnd = {
            "active": funnel.dnd_active(now_ts()) is not None,
            "until": dnd_until,                       # 临时 DND 到期时间戳,无则 None
            "until_str": to_str(dnd_until),           # 人话,供直接显示
            "night_end": settings_mod.get("dnd_night_end"),
        }
        return {"layers": layers, "will_push": will_push,
                "poll_interval": settings_mod.get("poll_interval"), "dnd": dnd}

    @app.put("/api/dnd")
    def api_dnd_set(body: DndIn):
        """开临时免打扰:传 until('YYYY-MM-DD HH:MM' 到期时刻)。返回当前 until 时间戳。"""
        settings_mod.set_dnd_until(to_ts(body.until))
        until = settings_mod.get_dnd_until()
        events.publish("dnd", until=until)
        return {"until": until}

    @app.delete("/api/dnd")
    def api_dnd_clear():
        """立即恢复:清掉临时免打扰。"""
        settings_mod.set_dnd_until(None)
        events.publish("dnd", until=None)
        return {"until": None}

    # ---------- AI 层(第四层) ----------

    @app.get("/api/ai/log")
    def api_ai_log(limit: int = 100):
        """AI 调用过程日志(供浮窗「AI 看了啥」展示)。倒序,最新在前。"""
        from . import agent as agent_mod
        return {"entries": agent_mod.read_log(limit)}

    @app.get("/api/ai/history")
    def api_ai_history(limit: int = 50):
        """对话历史(供浮窗重载后回填)。正序,只含 user_reply/speak。"""
        from . import agent as agent_mod
        return {"entries": agent_mod.read_history(limit)}

    @app.post("/api/ai/reply")
    def api_ai_reply(body: AiReplyIn):
        """用户在浮窗回 AI 一句:转发给 Agent 接话。"""
        from . import agent as agent_mod
        agent_mod.get_agent().reply(body.text)
        return {"ok": True}

    @app.get("/api/ai/status")
    def api_ai_status():
        """AI 助手总开关当前状态(供浮窗启动时决定显隐左列)。"""
        return {"enabled": settings_mod.get_ai_enabled()}

    @app.post("/api/ai/toggle")
    def api_ai_toggle(body: dict):
        """开/关 AI 助手。enabled=False → judge 不再发 LLM 请求,省费用。
        不动 Agent 线程/订阅:judge 下次被调自然读到新值,被拦即返空串。"""
        enabled = bool(body.get("enabled"))
        settings_mod.set_ai_enabled(enabled)
        return {"enabled": settings_mod.get_ai_enabled()}

    @app.websocket("/ws")
    async def ws(ws: WebSocket):
        """事件推送通道:浮窗/未来 AI 订阅,被动接收 notify/done/snooze/dnd 等事件。"""
        await events.register(ws)
        try:
            while True:
                await ws.receive_text()      # 客户端目前不主动发,只保活/收断开
        except WebSocketDisconnect:
            pass
        finally:
            events.unregister(ws)

    _mount_static(app)
    return app


def _days_to_secs(days):
    """前端传的「天数」-> 内部秒。None -> None。"""
    if days is None:
        return None
    return int(days * SECONDS_PER_DAY)


def _require_task(tid: str):
    """任务不存在则 404(写操作前置校验)。"""
    conn = queries.db.connect()
    try:
        if queries.db.get_task(conn, tid) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
    finally:
        conn.close()


def _task_title(conn, tid: str):
    """取任务标题(供事件携带,让 AI 订阅者免回查)。任务没了则 None。"""
    task = queries.db.get_task(conn, tid)
    return task["title"] if task else None


def _mount_static(app: FastAPI):
    """托管前端构建产物。dist 不存在(还没 pnpm build)时跳过,只留 /api。"""
    if not WEB_DIST.exists():
        return

    assets = WEB_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # 未匹配的 /api/* 返回 404 JSON,而不是回退 index.html——
        # 否则前端调错路径会拿到 200+HTML,静默失败、页面空白无提示。
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"接口不存在: /{full_path}")
        # 命中的真实文件(如 favicon)直接返回;否则回退 index.html 交给前端路由
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")


app = create_app()


def run(port: int):
    """供托盘/主程序在子线程里拉起服务。

    log_config=None:不让 uvicorn 初始化自己的日志 formatter。
    否则在 pythonw(无窗口,sys.stdout 为 None)下,
    uvicorn 的 formatter 调 sys.stdout.isatty() 会直接 AttributeError 崩掉,
    服务永远起不来。面板服务本就不需要 uvicorn 的访问日志。
    """
    import uvicorn
    # 绑 0.0.0.0:默认对局域网开放(手机/同 WiFi 设备可访问面板)。
    # 本地 pywebview 浮窗仍用 127.0.0.1 加载页面(notify_window.py),不受影响。
    uvicorn.run(app, host="0.0.0.0", port=port,
                log_level="warning", log_config=None)
