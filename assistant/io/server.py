"""FastAPI 面板服务:喂数据给 WebUI,并托管前端构建产物。

属于 io 层:只读 core/queries 已加工的数据,不含业务逻辑。

路由:
- GET /api/tasks  → {'starts': [...], 'ends': [...], 'tags': [...]}(只读面板数据)
- GET /           → frontend/dist/index.html(生产模式,chrome --app 直接打这里)
- 其余静态资源   → frontend/dist 下的 assets

开发模式则另起 `pnpm dev`(Vite 把 /api 代理到本服务),不走静态托管。
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import WEB_DIST
from ..core import queries


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

    _mount_static(app)
    return app


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
