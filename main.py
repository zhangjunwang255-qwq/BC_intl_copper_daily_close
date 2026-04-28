"""
铜差比价后端API - 主入口
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import latest, history, backfill
from app.db.database import engine, Base
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时创建数据库表
    Base.metadata.create_all(bind=engine)
    # 启动定时任务
    start_scheduler()
    yield
    # 关闭时停止定时任务
    stop_scheduler()


app = FastAPI(
    title="CopperSpreadMotion API",
    description="沪铜(CU)与国际铜(BC)比价展示后端",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(latest.router, prefix="/api", tags=["数据查询"])
app.include_router(history.router, prefix="/api", tags=["历史数据"])
app.include_router(backfill.router, prefix="/api", tags=["数据回填"])


@app.get("/")
async def root():
    return {"message": "CopperSpreadMotion API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}