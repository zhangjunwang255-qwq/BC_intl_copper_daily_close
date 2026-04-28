"""数据回填 API"""
import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.price import BackfillResponse
from app.services.backfill import run_backfill_task

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/backfill", response_model=BackfillResponse)
async def start_backfill(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """启动历史回填任务"""
    # 将任务添加到后台执行
    background_tasks.add_task(run_backfill_task, db)
    
    return BackfillResponse(
        status="started",
        message="历史回填任务已启动，请在后台查看进度"
    )