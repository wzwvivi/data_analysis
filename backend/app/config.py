# -*- coding: utf-8 -*-
"""应用配置"""
import os
from pathlib import Path

# 基础路径: 支持环境变量覆盖(Docker), 也兼容本地开发
_file_based = Path(__file__).resolve().parent.parent
_cwd_based = Path(os.getcwd()).resolve()

if os.environ.get("APP_BASE_DIR"):
    BASE_DIR = Path(os.environ["APP_BASE_DIR"])
elif (_cwd_based / "app" / "main.py").exists():
    BASE_DIR = _cwd_based
elif (_cwd_based / "backend" / "app" / "main.py").exists():
    BASE_DIR = _cwd_based / "backend"
else:
    BASE_DIR = _file_based

UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"

UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DATA_DIR.mkdir(exist_ok=True, parents=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR}/tsn_analyzer.db"

print(f"[Config] BASE_DIR = {BASE_DIR}")
print(f"[Config] DATABASE = {DATA_DIR}/tsn_analyzer.db")
print(f"[Config] DB exists = {(DATA_DIR / 'tsn_analyzer.db').exists()}")

# 文件上传配置
MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
ALLOWED_EXTENSIONS = {".pcapng", ".pcap", ".cap"}

# 协议库配置
PROTOCOL_EXCEL_EXTENSIONS = {".xlsx", ".xls"}
