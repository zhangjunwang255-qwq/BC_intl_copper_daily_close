"""历史数据回填服务"""
import logging
import os
from datetime import date, timedelta
from typing import Optional
from tqsdk import TqApi, TqAuth
from sqlalchemy.orm import Session
from app.models.price import PriceRecord
from app.services.price_service import get_current_contracts

logger = logging.getLogger(__name__)


def is_trading_day(d: date) -> bool:
    """简单判断是否可能是交易日（排除周六日）"""
    return d.weekday() < 5


def fetch_historical_close(api: TqApi, contract_code: str, target_date: date) -> Optional[float]:
    """
    获取指定合约在指定日期的收盘价
    使用 get_kline_serial 获取历史K线
    """
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        # 获取日K线，从目标日期开始取1根
        klines = api.get_kline_serial(
            contract_code,
            duration_seconds=86400,  # 日线
            start_dt=date_str,
            end_dt=(target_date + timedelta(days=1)).strftime("%Y-%m-%d")
        )
        # 等待数据到达
        api.wait_update(klines)
        
        if len(klines) > 0:
            close_price = klines.close.iloc[-1]
            if close_price and not (isinstance(close_price, float) and close_price != close_price):
                logger.info(f"  {contract_code} {date_str} 收盘价: {close_price}")
                return float(close_price)
        
        logger.warning(f"  {contract_code} {date_str} 无有效收盘价")
        return None
    except Exception as e:
        logger.warning(f"  {contract_code} {date_str} 获取失败: {e}")
        return None


def run_backfill_task(db: Session):
    """执行历史回填任务：从 2026-03-01 到昨天"""
    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        logger.warning("回填日期范围无效")
        return

    logger.info(f"========== 历史回填开始 ==========")
    logger.info(f"日期范围: {start_date} ~ {end_date}")

    # 构建交易日列表
    trading_days = []
    d = start_date
    while d <= end_date:
        if is_trading_day(d):
            trading_days.append(d)
        d += timedelta(days=1)

    logger.info(f"预计处理 {len(trading_days)} 个交易日")

    # 直接用 auth=TqAuth，不传 account 参数（TqSdk 自动用模拟账号）
    if TQ_USER and TQ_PASSWORD:
        api = TqApi(auth=TqAuth(TQ_USER, TQ_PASSWORD))
    else:
        api = TqApi()  # 无账号时用默认模拟账号

    try:
        for i, current_date in enumerate(trading_days):
            date_str = current_date.strftime("%Y-%m-%d")
            logger.info(f"[{i+1}/{len(trading_days)}] 处理 {date_str}...")

            cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
            contracts = [cu_main, cu_next, bc_main, bc_next]

            for contract in contracts:
                price = fetch_historical_close(api, contract, current_date)

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
                    logger.info(f"  ✓ {contract}: {price}")
                else:
                    logger.warning(f"  ✗ {contract}: 无有效价格")

            # 每50天报告进度
            if (i + 1) % 50 == 0:
                logger.info(f"进度: {i+1}/{len(trading_days)}")

    except Exception as e:
        logger.error(f"历史回填任务失败: {e}")
    finally:
        api.close()

    logger.info("========== 历史回填完成 ==========")


def auto_backfill_on_startup(db: Session):
    """启动时检查并自动回填缺失的历史数据（限制60天避免超时）"""
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
        # 限制每次最多回填30天，避免 Railway 超时
        days_to_fill = missing_days[:30]
        logger.info(f"本次回填 {len(days_to_fill)} 天...")

        TQ_USER = os.getenv("TQ_USER", "")
        TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")

        if TQ_USER and TQ_PASSWORD:
            api = TqApi(auth=TqAuth(TQ_USER, TQ_PASSWORD))
        else:
            api = TqApi()

        try:
            for i, current_date in enumerate(days_to_fill):
                date_str = current_date.strftime("%Y-%m-%d")
                cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
                contracts = [cu_main, cu_next, bc_main, bc_next]

                for contract in contracts:
                    price = fetch_historical_close(api, contract, current_date)
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

                if (i + 1) % 10 == 0:
                    logger.info(f"回填进度: {i+1}/{len(days_to_fill)}...")

        except Exception as e:
            logger.error(f"回填失败: {e}")
        finally:
            api.close()

        if len(missing_days) > 30:
            logger.info(f"还有 {len(missing_days) - 30} 天未回填，将在下次启动时继续")
    else:
        logger.info("历史数据已完整，无需回填")
