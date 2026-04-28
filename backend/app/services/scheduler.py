"""定时任务调度器"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from app.services.price_service import fetch_current_prices, save_price_record, save_latest_price
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def fetch_and_save_prices():
    """定时获取并保存价格数据"""
    logger.info("开始定时获取价格数据...")
    
    db = SessionLocal()
    try:
        result = fetch_current_prices()
        if result.get("prices"):
            for contract, price in result["prices"].items():
                # 保存到 latest 表
                save_latest_price(db, contract, price)
                
                # 保存到历史记录表（今天）
                from datetime import date
                today = date.today().strftime("%Y-%m-%d")
                save_price_record(db, today, contract, price)
            
            logger.info(f"价格数据已更新: {result['prices']}")
        else:
            logger.warning("未获取到价格数据")
    except Exception as e:
        logger.error(f"定时任务执行失败: {e}")
    finally:
        db.close()


def start_scheduler():
    """启动定时任务（首次立即执行，之后每10分钟）"""
    from datetime import datetime
    scheduler.add_job(
        fetch_and_save_prices,
        trigger=IntervalTrigger(minutes=10),
        id="fetch_prices",
        name="获取价格数据",
        replace_existing=True,
        next_run_time=datetime.now()  # 立即执行首次
    )
    scheduler.start()
    logger.info("定时任务已启动，首次执行中，之后每10分钟执行")


def stop_scheduler():
    """停止定时任务"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("定时任务已停止")