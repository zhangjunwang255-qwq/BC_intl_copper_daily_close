"""历史数据回填服务"""
import logging
import os
from datetime import date, timedelta
from tqsdk import TqApi, TqAuth, TqBacktest
from sqlalchemy.orm import Session
from app.models.price import PriceRecord
from app.services.price_service import get_current_contracts

logger = logging.getLogger(__name__)


def is_trading_day(d: date) -> bool:
    """简单判断是否可能是交易日（排除周六日）"""
    return d.weekday() < 5


def fetch_contract_price(api, contract_code: str, target_date: str):
    """
    获取指定日期收盘价，优先级：close > last_price > pre_close
    返回 None 表示获取失败
    """
    try:
        quote = api.get_quote(contract_code)
        # 等待数据就绪（TqSdk 异步，需要 await 数据到达）
        api.wait_task(quote.diff_task)
        
        price = None
        # 尝试多个字段
        for field in ["close", "last_price", "pre_close"]:
            val = getattr(quote, field, None)
            if val is not None and not (isinstance(val, float) and val != val):  # NaN check
                price = float(val)
                logger.info(f"  {contract_code} 使用 {field}={price}")
                break
        
        return price
    except Exception as e:
        logger.warning(f"  {contract_code} 获取价格失败: {e}")
        return None


def run_backfill_task(db: Session):
    """执行历史回填任务：从 2026-03-01 到昨天，逐日获取收盘价并存入数据库"""
    TQ_USER = os.getenv("TQ_USER", "")
    TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")

    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        logger.warning("回填日期范围无效")
        return

    logger.info(f"========== 历史回填开始 ==========")
    logger.info(f"日期范围: {start_date} ~ {end_date}，共 {(end_date - start_date).days + 1} 天")

    # 构建交易日列表（提前过滤）
    trading_days = []
    d = start_date
    while d <= end_date:
        if is_trading_day(d):
            trading_days.append(d)
        d += timedelta(days=1)
    
    logger.info(f"预计处理 {len(trading_days)} 个交易日")

    try:
        auth = (TQ_USER, TQ_PASSWORD) if TQ_USER else None
        
        # 每次只查一个日期，创建独立 TqApi 实例，避免长时间占用
        for i, current_date in enumerate(trading_days):
            date_str = current_date.strftime("%Y-%m-%d")
            logger.info(f"[{i+1}/{len(trading_days)}] 处理 {date_str}...")
            
            cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
            contracts = [cu_main, cu_next, bc_main, bc_next]

            # 每个日期用独立 TqApi 连接
            try:
                api = TqApi(auth=auth)
                
                for contract in contracts:
                    price = fetch_contract_price(api, contract, date_str)
                    
                    if price is not None:
                        existing = db.query(PriceRecord).filter(
                            PriceRecord.date == date_str,
                            PriceRecord.contract_code == contract
                        ).first()

                        if existing:
                            existing.price = price
                            logger.info(f"  ✓ 更新 {contract}: {price}")
                        else:
                            db.add(PriceRecord(date=date_str, contract_code=contract, price=price))
                            logger.info(f"  ✓ 新增 {contract}: {price}")
                        
                        db.commit()
                    else:
                        logger.warning(f"  ✗ {contract} 无有效价格")

                api.close()
                api = None  # 避免 reuse

            except Exception as e:
                logger.error(f"  日期 {date_str} 处理失败: {e}")
                try:
                    if api:
                        api.close()
                except:
                    pass

            # 每100天报告进度
            if (i + 1) % 50 == 0:
                logger.info(f"进度: {i+1}/{len(trading_days)}，继续中...")

        logger.info("========== 历史回填完成 ==========")

    except Exception as e:
        logger.error(f"历史回填任务失败: {e}")


def auto_backfill_on_startup(db: Session):
    """启动时检查是否有未回填的历史数据，有则自动触发回填"""
    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        return

    existing_dates = set(r[0] for r in db.query(PriceRecord.date).distinct().all())

    missing_days = []
    d = start_date
    while d <= end_date:
        if is_trading_day(d):
            d_str = d.strftime("%Y-%m-%d")
            if d_str not in existing_dates:
                missing_days.append(d)
        d += timedelta(days=1)

    logger.info(f"数据库已有 {len(existing_dates)} 天数据，缺失 {len(missing_days)} 天")

    if missing_days:
        # 限制每次最多回填60天，避免 Railway 超时
        days_to_fill = missing_days[:60]
        logger.info(f"本次回填 {len(days_to_fill)} 天...")
        
        TQ_USER = os.getenv("TQ_USER", "")
        TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")
        auth = (TQ_USER, TQ_PASSWORD) if TQ_USER else None

        for i, current_date in enumerate(days_to_fill):
            date_str = current_date.strftime("%Y-%m-%d")
            cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
            contracts = [cu_main, cu_next, bc_main, bc_next]

            try:
                api = TqApi(auth=auth)
                for contract in contracts:
                    price = fetch_contract_price(api, contract, date_str)
                    if price is not None:
                        existing = db.query(PriceRecord).filter(
                            PriceRecord.date == date_str,
                            PriceRecord.contract_code == contract
                        ).first()
                        if existing:
                            existing.price = price
                        else:
                            db.add(PriceRecord(date=date_str, contract_code=contract, price=price))
                        db.commit()
                        logger.info(f"✓ {date_str} {contract}: {price}")
                    else:
                        logger.warning(f"✗ {date_str} {contract}: 无有效价格")
                api.close()
                api = None
            except Exception as e:
                logger.error(f"日期 {date_str} 回填失败: {e}")
                try:
                    if api:
                        api.close()
                except:
                    pass

            if (i + 1) % 50 == 0:
                logger.info(f"回填进度: {i+1}/{len(days_to_fill)}...")

        if len(missing_days) > 60:
            logger.info(f"还有 {len(missing_days) - 60} 天未回填，将在下次启动时继续")
    else:
        logger.info("历史数据已完整，无需回填")