"""FastAPI 面板服务:喂数据给 WebUI,并托管前端构建产物。

属于 io 层:只读 core/queries 已加工的数据,不含业务逻辑。

路由:
- GET /api/tasks  → {'starts': [...], 'ends': [...], 'tags': [...]}(只读面板数据)
- GET /           → frontend/dist/index.html(生产模式,chrome --app 直接打这里)
- 其余静态资源   → frontend/dist 下的 assets

开发模式则另起 `pnpm dev`(Vite 把 /api 代理到本服务),不走静态托管。
"""
from pathlib import Path

from fastapi import FastAPI
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
    """供托盘/主程序在子线程里拉起服务。"""
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
