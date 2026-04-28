"""历史数据回填服务"""
import logging
import os
from datetime import date, timedelta
from tqsdk import TqApi, TqAuth
from sqlalchemy.orm import Session
from app.models.price import PriceRecord
from app.services.price_service import get_current_contracts

logger = logging.getLogger(__name__)


def is_trading_day(d: date) -> bool:
    """简单判断是否可能是交易日（排除周六日，实际需排除节假日）"""
    return d.weekday() < 5


def run_backfill_task(db: Session):
    """执行历史回填任务：从 2026-03-01 到昨天，逐日获取收盘价并存入数据库"""
    TQ_USER = os.getenv("TQ_USER", "")
    TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")

    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        logger.warning("回填日期范围无效")
        return

    logger.info(f"开始历史回填: {start_date} ~ {end_date}，共 {(end_date - start_date).days + 1} 天")

    # 跳过非交易日（简单版：只跳过周末）
    # 历史节假日需要自行处理，这里用前后最近交易日替代
    try:
        auth = (TQ_USER, TQ_PASSWORD) if TQ_USER else None
        api = TqApi(auth=auth)

        current_date = start_date
        filled = 0
        skipped = 0

        while current_date <= end_date:
            if not is_trading_day(current_date):
                current_date += timedelta(days=1)
                continue

            cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
            contracts = [cu_main, cu_next, bc_main, bc_next]
            date_str = current_date.strftime("%Y-%m-%d")

            for contract in contracts:
                try:
                    quote = api.get_quote(contract)
                    price = getattr(quote, "close", None) or getattr(quote, "last_price", None)

                    if price and price != float("nan"):
                        existing = db.query(PriceRecord).filter(
                            PriceRecord.date == date_str,
                            PriceRecord.contract_code == contract
                        ).first()

                        if existing:
                            existing.price = float(price)
                        else:
                            db.add(PriceRecord(date=date_str, contract_code=contract, price=float(price)))

                        db.commit()
                        logger.info(f"✓ {date_str} {contract}: {price}")
                        filled += 1
                    else:
                        logger.warning(f"✗ {date_str} {contract}: 价格无效，跳过")
                except Exception as e:
                    logger.warning(f"✗ {date_str} {contract} 获取失败: {e}")

            current_date += timedelta(days=1)

        api.close()
        logger.info(f"历史回填完成：成功 {filled} 条")

    except Exception as e:
        logger.error(f"历史回填任务失败: {e}")


def auto_backfill_on_startup(db: Session):
    """启动时检查是否有未回填的历史数据，有则自动触发回填"""
    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    # 检查已有多少天的数据
    existing_dates = set(
        r[0] for r in db.query(PriceRecord.date).distinct().all()
    )

    missing_days = 0
    d = start_date
    while d <= end_date:
        if is_trading_day(d) and d.strftime("%Y-%m-%d") not in existing_dates:
            missing_days += 1
        d += timedelta(days=1)

    if missing_days > 0:
        logger.info(f"发现 {missing_days} 天历史数据缺失，启动自动回填...")
        run_backfill_task(db)
    else:
        logger.info("历史数据已完整，无需回填")