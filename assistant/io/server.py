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

接口文档:FastAPI 自带 /api/docs(Swagger)与 /api/openapi.json,AI 可自查。
开发模式另起 `pnpm dev`(Vite 代理 /api);生产模式由本服务托管 frontend/dist。
"""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import WEB_DIST
from ..core import actions, queries


# ---------- 请求体模型(Pydantic 校验 + 自动文档) ----------

class AddTaskIn(BaseModel):
    title: str
    drive: str = Field(pattern="^(start|end)$")
    deadline: Optional[str] = None      # end 驱动:'YYYY-MM-DD HH:MM'
    anchor: Optional[str] = None        # start 驱动:'YYYY-MM-DD',缺省取今天
    cycle_days: Optional[int] = None    # 周期天数;设置即视为周期任务
    is_cyclic: int = 0
    priority: int = 3
    note: Optional[str] = None
    tags: list[str] = []


class UpdateTaskIn(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    priority: Optional[int] = None
    deadline: Optional[str] = None
    anchor: Optional[str] = None
    cycle_days: Optional[int] = None


def create_app() -> FastAPI:
    app = FastAPI(title="Claude Assistant")

    @app.get("/api/tasks")
    def api_tasks():
        conn = queries.db.connect()
        try:
            data = queries.dashboard_data(conn)
            data["tags"] = queries.all_tags(conn)
            return data
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
        # 传了 cycle_days 即视为周期任务(更直觉,不必显式传 is_cyclic)
        payload = body.model_dump()
        if payload.get("cycle_days"):
            payload["is_cyclic"] = 1
        conn = queries.db.connect()
        try:
            return actions.do_add(conn, payload)
        finally:
            conn.close()

    @app.put("/api/tasks/{tid}")
    def api_update(tid: str, body: UpdateTaskIn):
        _require_task(tid)
        payload = {k: v for k, v in body.model_dump().items() if v is not None}
        conn = queries.db.connect()
        try:
            return actions.do_update(conn, {"task_id": tid, **payload})
        finally:
            conn.close()

    @app.post("/api/tasks/{tid}/done")
    def api_done(tid: str):
        _require_task(tid)
        conn = queries.db.connect()
        try:
            return actions.do_done(conn, {"task_id": tid})
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
    def api_snooze(tid: str):
        _require_task(tid)
        conn = queries.db.connect()
        try:
            return actions.do_snooze(conn, {"task_id": tid})
        finally:
            conn.close()

    _mount_static(app)
    return app


def _require_task(tid: str):
    """任务不存在则 404(写操作前置校验)。"""
    conn = queries.db.connect()
    try:
        if queries.db.get_task(conn, tid) is None:
            raise HTTPException(status_code=404, detail="任务不存在")
    finally:
        conn.close()


def _mount_static(app: FastAPI):
    """托管前端构建产物。dist 不存在(还没 pnpm build)时跳过,只留 /api。"""
    if not WEB_DIST.exists():
        return

    assets = WEB_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
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
    uvicorn.run(app, host="127.0.0.1", port=port,
                log_level="warning", log_config=None)
