# -*- coding: utf-8 -*-
"""FastAPI 主应用"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import init_db, async_session
from .routers import (
    protocol_router,
    parse_router,
    fms_event_analysis_router,
    event_analysis_router,
    fcc_event_analysis_router,
    auto_flight_analysis_router,
    compare_router,
    auth_router,
    shared_tsn_router,
    arinc429_router,
    role_config_router,
    network_config_router,
    device_protocol_router,
    notifications_router,
    dashboard_router,
    workbench_router,
    configuration_router,
)
from .config import UPLOAD_DIR, DATA_DIR, FLIGHT_ASSISTANT_URL
from .init_data import init_all_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    
    # 初始化内置数据（用户、解析版本配置等）并清理过期平台共享 TSN + 过期解析结果
    async with async_session() as db:
        await init_all_data(db)
        from .services.shared_tsn_service import purge_expired_shared_files
        from .services.disk_maintenance import purge_expired_results, free_disk_mb

        await purge_expired_shared_files(db)
        await purge_expired_results(db)
        mb = free_disk_mb()
        if mb >= 0:
            print(f"[DiskMaint] 启动体检: UPLOAD_DIR 剩余 {mb} MB")
    
    # 确保目录存在
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / "standalone_events").mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / "shared_tsn").mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "results").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "exports").mkdir(parents=True, exist_ok=True)
    
    yield
    # 关闭时的清理工作（如果需要）


app = FastAPI(
    title="TSN日志分析平台",
    description="TSN数据包解析与分析平台",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(shared_tsn_router)
app.include_router(arinc429_router)
app.include_router(role_config_router)
app.include_router(protocol_router)
app.include_router(network_config_router)
app.include_router(device_protocol_router)
app.include_router(notifications_router)
app.include_router(parse_router)
app.include_router(fms_event_analysis_router)
app.include_router(event_analysis_router)  # Phase 1 back-compat shim
app.include_router(fcc_event_analysis_router)
app.include_router(auto_flight_analysis_router)
app.include_router(compare_router)
app.include_router(dashboard_router)
app.include_router(workbench_router)
app.include_router(configuration_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "TSN日志分析平台",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@app.get("/api/config")
async def public_config():
    """前端启动需要的公共配置 (无鉴权)。

    目前只包含飞行助手分析的外链 URL；未启用时返回空字符串，前端据此
    隐藏菜单入口。真正访问控制仍依赖网络层 (参见 README 安全说明)。
    """
    return {
        "flight_assistant_url": FLIGHT_ASSISTANT_URL,
    }
