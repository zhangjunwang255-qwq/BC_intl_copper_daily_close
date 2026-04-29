"""历史数据回填服务 - 批量拉取版本"""
import logging
import os
from datetime import date, timedelta
from tqsdk import TqApi, TqAuth
from sqlalchemy.orm import Session
from app.models.price import PriceRecord
from app.services.price_service import get_current_contracts

logger = logging.getLogger(__name__)

# 天勤账户配置
TQ_USER = os.getenv("TQ_USER", "")
TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")


def is_trading_day(d: date) -> bool:
    """简单判断是否可能是交易日（排除周六日）"""
    return d.weekday() < 5


def run_backfill_task(db: Session):
    """批量拉取版本的历史回填任务
    
    核心思路：
    1. 计算日期范围内所有需要的合约（去重，通常6-8个）
    2. 每个合约一次 get_kline_serial(data_length=8000) 拉全量
    3. 统一 wait_update() 一次
    4. 内存中按日期匹配，写入库
    网络调用：从 200次 → 4-8次
    """
    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        logger.warning("回填日期范围无效")
        return

    logger.info(f"========== 历史回填开始 ==========")
    logger.info(f"日期范围: {start_date} ~ {end_date}")

    # ===== 第1步：计算交易日列表 =====
    trading_days = []
    d = start_date
    while d <= end_date:
        if is_trading_day(d):
            trading_days.append(d)
        d += timedelta(days=1)

    logger.info(f"预计处理 {len(trading_days)} 个交易日")

    # ===== 第2步：计算所有需要用到的合约（去重）=====
    all_contracts = set()
    for current_date in trading_days:
        cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
        all_contracts.update([cu_main, cu_next, bc_main, bc_next])

    contract_list = sorted(all_contracts)
    logger.info(f"需要拉取的合约 ({len(contract_list)} 个): {contract_list}")

    # ===== 第3步：TqApi 连接一次 =====
    if TQ_USER and TQ_PASSWORD:
        api = TqApi(auth=TqAuth(TQ_USER, TQ_PASSWORD))
    else:
        api = TqApi()

    # 存储所有合约的K线数据: {contract: Klines对象}
    all_klines = {}

    try:
        # ===== 第4步：批量注册所有合约的K线订阅 =====
        logger.info("📡 批量注册合约订阅...")
        for contract in contract_list:
            # 一次拉8000根日线（约30年，绰绰有余）
            klines = api.get_kline_serial(
                contract,
                duration_seconds=86400,  # 日线
                data_length=8000
            )
            all_klines[contract] = klines

        # ===== 第5步：统一 wait_update() 等所有数据到位 =====
        logger.info("⏳ 等待数据返回（可能需要10-30秒）...")
        # 循环等待直到所有合约数据就绪
        max_wait_seconds = 120
        wait_interval = 5
        waited = 0
        while waited < max_wait_seconds:
            api.wait_update()
            
            # 检查所有合约是否数据就绪
            all_ready = True
            for contract, klines in all_klines.items():
                if not api.is_serial_ready(klines):
                    all_ready = False
                    break
            
            if all_ready:
                break
            
            waited += wait_interval
            logger.info(f"  已等待 {waited}s...")
        
        if waited >= max_wait_seconds:
            logger.warning("⚠️ 等待超时，部分数据可能未完整")

        # ===== 第6步：在内存���构建 {date: {contract: price}} 映射 =====
        logger.info("📊 构建价格映射表...")
        price_map = {}  # {(date_str, contract): price}

        for contract, klines in all_klines.items():
            if len(klines) == 0:
                logger.warning(f"  {contract}: 无K线数据")
                continue

            # 遍历K线数据
            for idx in range(len(klines)):
                try:
                    dt = klines.datetime.iloc[idx]
                    close = klines.close.iloc[idx]
                    
                    if dt is None:
                        continue
                    # dt 是 Timestamp 或类似对象，转成 date
                    if hasattr(dt, 'date'):
                        trade_date = dt.date()
                    else:
                        # 可能是字符串 "2026-01-15 00:00:00"
                        trade_date = date.fromisoformat(str(dt).date() if isinstance(dt, str) else None
                    
                    if trade_date is None:
                        continue
                    
                    # 跳过非交易日的无效数据
                    if isinstance(close, float) and close != close:  # NaN check
                        continue
                    if close is None or close <= 0:
                        continue
                    
                    date_str = trade_date.strftime("%Y-%m-%d")
                    price_map[(date_str, contract)] = float(close)
                except Exception as e:
                    # 跳过错误行
                    continue

        logger.info(f"  共获取 {len(price_map)} 条价格记录")

        # ===== 第7步：按交易日遍历，匹配合约，写入库 =====
        logger.info("💾 写入数据库...")
        write_count = 0
        
        for i, current_date in enumerate(trading_days):
            date_str = current_date.strftime("%Y-%m-%d")
            cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
            contracts = [cu_main, cu_next, bc_main, bc_next]

            for contract in contracts:
                price = price_map.get((date_str, contract))
                if price is not None:
                    # 检查是否已存在
                    existing = db.query(PriceRecord).filter(
                        PriceRecord.date == date_str,
                        PriceRecord.contract_code == contract
                    ).first()

                    if existing:
                        existing.price = price
                    else:
                        db.add(PriceRecord(date=date_str, contract_code=contract, price=price))
                    write_count += 1

            # 每50天提交一次
            if (i + 1) % 50 == 0 or i == len(trading_days) - 1:
                db.commit()
                logger.info(f"  进度: {i+1}/{len(trading_days)}，已写入 {write_count} 条")

        logger.info(f"✅ 历史回填完成，共写入 {write_count} 条记录")

    except Exception as e:
        logger.error(f"历史回填任务失败: {e}", exc_info=True)
        db.rollback()
    finally:
        api.close()

    logger.info("========== 历史回填完成 ==========")


def auto_backfill_on_startup(db: Session):
    """启动时检查并自动回填缺失的历史数据（限制60天避免超时）"""
    start_date = date(2026, 3, 1)
    end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        return

    # 检查已有数据的日期
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

    if not missing_days:
        logger.info("历史数据已完整，无需回填")
        return

    # 限制每次最多回填30天
    days_to_fill = missing_days[:30]
    logger.info(f"本次回填 {len(days_to_fill)} 天...")

    # ===== 同样的批量拉取逻辑 =====
    all_contracts = set()
    for current_date in days_to_fill:
        cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
        all_contracts.update([cu_main, cu_next, bc_main, bc_next])

    contract_list = sorted(all_contracts)

    if TQ_USER and TQ_PASSWORD:
        api = TqApi(auth=TqAuth(TQ_USER, TQ_PASSWORD))
    else:
        api = TqApi()

    all_klines = {}

    try:
        # 批量注册
        for contract in contract_list:
            klines = api.get_kline_serial(contract, duration_seconds=86400, data_length=8000)
            all_klines[contract] = klines

        # 统一等待
        max_wait_seconds = 120
        waited = 0
        while waited < max_wait_seconds:
            api.wait_update()
            all_ready = True
            for contract, klines in all_klines.items():
                if not api.is_serial_ready(klines):
                    all_ready = False
                    break
            if all_ready:
                break
            waited += 5

        # 构建价格映射
        price_map = {}
        for contract, klines in all_klines.items():
            if len(klines) == 0:
                continue
            for idx in range(len(klines)):
                try:
                    dt = klines.datetime.iloc[idx]
                    close = klines.close.iloc[idx]
                    if dt is None:
                        continue
                    if hasattr(dt, 'date'):
                        trade_date = dt.date()
                    else:
                        trade_date = date.fromisoformat(str(dt)).date() if isinstance(dt, str) else None
                    if trade_date is None:
                        continue
                    if isinstance(close, float) and close != close:
                        continue
                    if close is None or close <= 0:
                        continue
                    date_str = trade_date.strftime("%Y-%m-%d")
                    price_map[(date_str, contract)] = float(close)
                except:
                    continue

        # 写入
        write_count = 0
        for i, current_date in enumerate(days_to_fill):
            date_str = current_date.strftime("%Y-%m-%d")
            cu_main, cu_next, bc_main, bc_next = get_current_contracts(current_date)
            contracts = [cu_main, cu_next, bc_main, bc_next]

            for contract in contracts:
                price = price_map.get((date_str, contract))
                if price is not None:
                    existing = db.query(PriceRecord).filter(
                        PriceRecord.date == date_str,
                        PriceRecord.contract_code == contract
                    ).first()
                    if existing:
                        existing.price = price
                    else:
                        db.add(PriceRecord(date=date_str, contract_code=contract, price=price))
                    write_count += 1

            if (i + 1) % 10 == 0:
                db.commit()
                logger.info(f"回填进度: {i+1}/{len(days_to_fill)}")

        db.commit()
        logger.info(f"✅ 启动回填完成，写入 {write_count} 条")

        if len(missing_days) > 30:
            logger.info(f"还有 {len(missing_days) - 30} 天未回填，将在下次启动时继续")

    except Exception as e:
        logger.error(f"回填失败: {e}", exc_info=True)
    finally:
        api.close()