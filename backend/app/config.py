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

# 认证（生产环境务必设置环境变量）
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-change-me-use-env-jwt-secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))  # 默认 7 天

# 平台共享 TSN：管理员上传文件保留天数
SHARED_TSN_RETENTION_DAYS = int(os.environ.get("SHARED_TSN_RETENTION_DAYS", "2"))

# 服务器核数（用于推导重任务进程池默认并发；可直接由环境变量覆盖）
SERVER_CPU_CORES = int(os.environ.get("SERVER_CPU_CORES", "4"))

# 首次启动默认管理员（若库中无任何用户则创建；密码可用环境变量覆盖）
INIT_ADMIN_USERNAME = os.environ.get("INIT_ADMIN_USERNAME", "admin")
INIT_ADMIN_PASSWORD = os.environ.get("INIT_ADMIN_PASSWORD", "admin123")
INIT_USER_USERNAME = os.environ.get("INIT_USER_USERNAME", "user")
INIT_USER_PASSWORD = os.environ.get("INIT_USER_PASSWORD", "user123")
