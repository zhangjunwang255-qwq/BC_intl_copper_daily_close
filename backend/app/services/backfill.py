"""历史数据回填服务"""
import logging
from datetime import datetime, date, timedelta
from tqsdk import TqApi
from sqlalchemy.orm import Session
from app.models.price import PriceRecord
from app.services.price_service import get_current_contracts, get_contract_price

logger = logging.getLogger(__name__)


def run_backfill_task(db: Session):
    """执行历史回填任务"""
    import os
    TQ_USER = os.getenv("TQ_USER", "")
    TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")
    
    # 从 2026-03-01 到昨天
    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)
    
    if start_date > end_date:
        logger.warning("回填日期范围无效")
        return
    
    logger.info(f"开始历史回填: {start_date} 到 {end_date}")
    
    try:
        api = TqApi(user=TQ_USER, password=TQ_PASSWORD)
        
        current_date = start_date
        filled_count = 0
        
        while current_date <= end_date:
            # 跳过周末
            if current_date.weekday() < 5:  # 0-4 为周一到周五
                cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
                contracts = [cu_main, cu_next, bc_main, bc_next]
                
                for contract in contracts:
                    try:
                        # 尝试获取收盘价
                        quote = api.get_quote(contract)
                        # 使用昨收价或最新价
                        price = quote.last_price or quote.pre_close
                        
                        if price:
                            date_str = current_date.strftime("%Y-%m-%d")
                            
                            # 检查是否已存在
                            existing = db.query(PriceRecord).filter(
                                PriceRecord.date == date_str,
                                PriceRecord.contract_code == contract
                            ).first()
                            
                            if existing:
                                existing.price = price
                            else:
                                record = PriceRecord(
                                    date=date_str,
                                    contract_code=contract,
                                    price=price
                                )
                                db.add(record)
                            
                            db.commit()
                            filled_count += 1
                            logger.info(f"已回填 {date_str} {contract}: {price}")
                    except Exception as e:
                        logger.warning(f"获取 {contract} 数据失败: {e}")
            
            current_date += timedelta(days=1)
        
        api.close()
        logger.info(f"历史回填完成，共填充 {filled_count} 条记录")
        
    except Exception as e:
        logger.error(f"历史回填任务失败: {e}")