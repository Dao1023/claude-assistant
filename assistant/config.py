"""配置与路径常量(最底层,谁也不 import 其他模块)"""
from pathlib import Path

BASE = Path(__file__).parent.parent          # 项目根目录
DATA = BASE / "data"                         # 运行期数据目录(进 .gitignore)
DATA.mkdir(exist_ok=True)

DB_PATH = DATA / "assistant.db"              # SQLite 数据库

# claude.exe 路径(winget 安装)
CLAUDE_EXE = r"C:\Users\Dao\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe\claude.exe"

VAULT = r"C:\Obsidian"                       # 唤起时的工作目录(Obsidian 库,已信任免确认)

# Chrome 路径(--app 模式打开面板)
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

APP_NAME = "Claude Assistant"
POLL_INTERVAL = 30                           # 轮询间隔(秒)

# WebUI 面板
WEB_PORT = 5174                              # FastAPI 服务端口(面板 + /api)
WEB_DIST = BASE / "frontend" / "dist"        # 前端构建产物(pnpm build 输出)

