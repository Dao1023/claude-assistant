"""配置与路径常量(最底层,谁也不 import 其他模块)"""
from pathlib import Path

BASE = Path(__file__).parent.parent          # 项目根目录
DATA = BASE / "data"                         # 运行期数据目录(进 .gitignore)
DATA.mkdir(exist_ok=True)

INBOX = DATA / "inbox.json"                  # 信箱文件(Claude Code ↔ APP 契约)
COMMANDS = DATA / "commands.json"            # 指令文件(Claude Code → APP)
DB_PATH = DATA / "assistant.db"              # SQLite 数据库

# claude.exe 路径(winget 安装)
CLAUDE_EXE = r"C:\Users\Dao\AppData\Local\Microsoft\WinGet\Packages\Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe\claude.exe"

VAULT = r"C:\Obsidian"                       # 唤起时的工作目录(Obsidian 库,已信任免确认)

APP_NAME = "Claude Assistant"
POLL_INTERVAL = 30                           # 轮询间隔(秒)
