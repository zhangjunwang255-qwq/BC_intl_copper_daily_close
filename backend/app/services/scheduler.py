"""定时任务调度器"""
import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from app.services.price_service import fetch_current_prices, save_price_record, save_latest_price
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def fetch_and_save_prices():
    """定时获取并保存价格数据"""
    import time
    logger.info("🕐 定时任务触发，开始获取价格数据...")
    
    db = SessionLocal()
    try:
        result = fetch_current_prices()
        prices = result.get("prices", {})
        
        if prices:
            logger.info(f"📊 获取到 {len(prices)} 个合约价格: {prices}")
            
            for contract, price in prices.items():
                # 保存到历史记录表（今天）
                from datetime import date
                today = date.today().strftime("%Y-%m-%d")
                save_price_record(db, today, contract, price)
                save_latest_price(db, contract, price)
            
            logger.info(f"✅ 价格数据已写入数据库")
        else:
            logger.warning("⚠️ 未获取到任何价格数据！")
            # 调试：检查 TqSdk 连接
            TQ_USER = os.getenv("TQ_USER", "")
            TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")
            from app.services.price_service import get_current_contracts
            cu_main, cu_next, bc_main, bc_next = get_current_contracts()
            logger.warning(f"  目标合约: {cu_main}, {cu_next}, {bc_main}, {bc_next}")
            logger.warning(f"  TQ_USER 已设置: {bool(TQ_USER)}")
    except Exception as e:
        logger.error(f"❌ 定时任务执行失败: {e}", exc_info=True)
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