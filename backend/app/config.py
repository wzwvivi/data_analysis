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
DRAFT_UPLOAD_DIR = UPLOAD_DIR / "drafts"

UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DATA_DIR.mkdir(exist_ok=True, parents=True)
DRAFT_UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR}/tsn_analyzer.db"

print(f"[Config] BASE_DIR = {BASE_DIR}")
print(f"[Config] DATABASE = {DATA_DIR}/tsn_analyzer.db")
print(f"[Config] DB exists = {(DATA_DIR / 'tsn_analyzer.db').exists()}")

# 文件上传配置
# 目标生产机 40GB 磁盘（剩 ~22GB），单次上传压到 2GB 防止磁盘写满。
# 需要上传更大文件时，通过环境变量覆盖: MAX_UPLOAD_SIZE_MB=5120 -> 5GB
_max_upload_mb = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "2048"))
MAX_UPLOAD_SIZE = _max_upload_mb * 1024 * 1024
ALLOWED_EXTENSIONS = {".pcapng", ".pcap", ".cap"}

# 解析结果（data/results/<task>/*.parquet）保留天数；0 表示不自动清理（默认永久保留）。
# 想启用自动清理就在 .env / 环境变量里把 RESULT_RETENTION_DAYS 设成 >0 的天数；
# 启用后：启动时以及每次新上传前都会触发一次过期回收。
RESULT_RETENTION_DAYS = int(os.environ.get("RESULT_RETENTION_DAYS", "0"))

# 上传前检查 UPLOAD_DIR 所在磁盘剩余空间；低于该阈值（MB）则拒绝新上传。
# 默认 2GB。设为 0 表示不检查。
MIN_FREE_DISK_MB = int(os.environ.get("MIN_FREE_DISK_MB", "2048"))

# 协议库配置
PROTOCOL_EXCEL_EXTENSIONS = {".xlsx", ".xls"}

# 认证（生产环境务必设置环境变量）
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-change-me-use-env-jwt-secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "168"))  # 默认 7 天

# 平台共享 TSN：管理员上传文件保留天数
SHARED_TSN_RETENTION_DAYS = int(os.environ.get("SHARED_TSN_RETENTION_DAYS", "2"))

# 飞行助手分析 (flight_data_webapp) 独立部署的外链 URL。
# 空字符串表示未启用, 前端菜单不会展示入口。
# 典型值: "http://<host>:8082" 或反向代理后的 "https://tsn.example.com/flight-assistant"
FLIGHT_ASSISTANT_URL = os.environ.get("FLIGHT_ASSISTANT_URL", "").strip()

# HEVC 入库时自动转 H.264（便于浏览器播放）；设为 0/false/no 关闭
VIDEO_TRANSCODE_HEVC = os.environ.get("VIDEO_TRANSCODE_HEVC", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# 服务器核数（用于推导重任务进程池默认并发；可直接由环境变量覆盖）
SERVER_CPU_CORES = int(os.environ.get("SERVER_CPU_CORES", "4"))

# 首次启动默认管理员（若库中无任何用户则创建；密码可用环境变量覆盖）
INIT_ADMIN_USERNAME = os.environ.get("INIT_ADMIN_USERNAME", "admin")
INIT_ADMIN_PASSWORD = os.environ.get("INIT_ADMIN_PASSWORD", "admin123")
INIT_USER_USERNAME = os.environ.get("INIT_USER_USERNAME", "user")
INIT_USER_PASSWORD = os.environ.get("INIT_USER_PASSWORD", "user123")
