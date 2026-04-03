# -*- coding: utf-8 -*-
"""FastAPI 主应用"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import init_db, async_session
from .routers import protocol_router, parse_router, event_analysis_router, compare_router
from .config import UPLOAD_DIR, DATA_DIR
from .init_data import init_all_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    
    # 初始化内置数据（解析版本配置等）
    async with async_session() as db:
        await init_all_data(db)
    
    # 确保目录存在
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / "standalone_events").mkdir(parents=True, exist_ok=True)
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
app.include_router(protocol_router)
app.include_router(parse_router)
app.include_router(event_analysis_router)
app.include_router(compare_router)


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
