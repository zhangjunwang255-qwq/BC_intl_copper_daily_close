"""核心业务逻辑服务"""
import os
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Tuple
from tqsdk import TqApi, TqAuth
from sqlalchemy.orm import Session

from app.models.price import PriceRecord, LatestPrice

logger = logging.getLogger(__name__)

# 天勤账户配置
TQ_USER = os.getenv("TQ_USER", "")
TQ_PASSWORD = os.getenv("TQ_PASSWORD", "")


def _add_months(base_date: date, months: int) -> date:
    """日期加N个月，返回对应月的任意一天（只关心年月）"""
    month = base_date.month - 1 + months
    year = base_date.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def get_current_contracts(day: date = None) -> Tuple[str, str, str, str]:
    """
    根据日期获取当前应选取的合约代码（带交易所前缀）
    规则：日>15 → M+2/M+3；日≤15 → M+1/M+2
    返回: (cu_main, cu_next, bc_main, bc_next)
    """
    if day is None:
        day = date.today()
    
    if day.day > 15:
        # M+2, M+3
        d2 = _add_months(day, 2)
        d3 = _add_months(day, 3)
        cu_main = f"SHFE.CU{d2.strftime('%y%m')}"
        cu_next = f"SHFE.CU{d3.strftime('%y%m')}"
        bc_main = f"INE.BC{d2.strftime('%y%m')}"
        bc_next = f"INE.BC{d3.strftime('%y%m')}"
    else:
        # M+1, M+2
        d1 = _add_months(day, 1)
        d2 = _add_months(day, 2)
        cu_main = f"SHFE.CU{d1.strftime('%y%m')}"
        cu_next = f"SHFE.CU{d2.strftime('%y%m')}"
        bc_main = f"INE.BC{d1.strftime('%y%m')}"
        bc_next = f"INE.BC{d2.strftime('%y%m')}"
    
    return cu_main, cu_next, bc_main, bc_next


def get_contract_price(api: TqApi, contract_code: str) -> Optional[float]:
    """获取合约最新价格，等待数据到达"""
    try:
        quote = api.get_quote(contract_code)
        # 不传参数，等所有数据更新一次
        api.wait_update()
        
        price = quote.last_price
        # NaN 或 None 时认为数据未到
        if price is None or (isinstance(price, float) and price != price):
            return None
        
        return float(price)
    except Exception as e:
        logger.warning(f"获取 {contract_code} 价格失败: {e}")
        return None


def fetch_current_prices() -> Dict[str, float]:
    """从TqSdk获取当前价格"""
    cu_main, cu_next, bc_main, bc_next = get_current_contracts()
    
    result = {
        "cu_main": cu_main,
        "cu_next": cu_next,
        "bc_main": bc_main,
        "bc_next": bc_next,
        "prices": {}
    }
    
    try:
        if TQ_USER and TQ_PASSWORD:
            api = TqApi(auth=TqAuth(TQ_USER, TQ_PASSWORD))
        else:
            api = TqApi()
        
        contracts = [cu_main, cu_next, bc_main, bc_next]
        quotes = {}
        
        # 注册订阅，捕获不存在合约
        for c in contracts:
            try:
                quotes[c] = api.get_quote(c)
            except Exception as e:
                logger.warning(f"{c} 不可用: {e}")
        
        # 等待数据到达，带超时
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                api.wait_update(deadline=deadline)
            except Exception as e:
                logger.warning(f"wait_update 异常: {e}")
                break
            
            all_ready = True
            for c, q in quotes.items():
                if not api.is_quote_ready(q):
                    all_ready = False
                    break
            if all_ready:
                break
        
        for contract, quote in quotes.items():
            try:
                price = quote.last_price
                if price is not None and not (isinstance(price, float) and price != price):
                    result["prices"][contract] = float(price)
                    logger.info(f"{contract} = {price}")
                else:
                    logger.warning(f"{contract} 数据未到: last_price={price}")
            except Exception as e:
                logger.warning(f"读取 {contract} 价格失败: {e}")
        
        api.close()
    except Exception as e:
        logger.error(f"获取价格失败: {e}")
    
    return result


def calculate_metrics(cu_price: float, bc_price: float) -> Dict[str, float]:
    """计算比价和价差指标"""
    if cu_price and bc_price:
        ratio = cu_price / bc_price
        spread = cu_price / 1.13 - bc_price
        return {"ratio": ratio, "spread": spread}
    return {"ratio": None, "spread": None}


def save_price_record(db: Session, date_str: str, contract_code: str, price: float) -> bool:
    """保存价格记录"""
    try:
        # 检查是否已存在
        existing = db.query(PriceRecord).filter(
            PriceRecord.date == date_str,
            PriceRecord.contract_code == contract_code
        ).first()
        
        if existing:
            existing.price = price
            existing.update_time = datetime.utcnow()
        else:
            record = PriceRecord(
                date=date_str,
                contract_code=contract_code,
                price=price
            )
            db.add(record)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"保存价格记录失败: {e}")
        db.rollback()
        return False


def save_latest_price(db: Session, contract_code: str, price: float) -> bool:
    """保存最新价格缓存"""
    try:
        existing = db.query(LatestPrice).filter(
            LatestPrice.contract_code == contract_code
        ).first()
        
        if existing:
            existing.price = price
            existing.update_time = datetime.utcnow()
        else:
            record = LatestPrice(contract_code=contract_code, price=price)
            db.add(record)
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"保存最新价格失败: {e}")
        db.rollback()
        return False


def get_latest_data(db: Session) -> Optional[Dict]:
    """获取当前最新数据"""
    today = date.today()
    cu_main, cu_next, bc_main, bc_next = get_current_contracts(today)
    
    result = {
        "date": today.strftime("%Y-%m-%d"),
        "cu_current": None,
        "bc_current": None,
        "ratio": None,
        "spread": None,
        "cu_next": None,
        "bc_next": None,
        "cu_diff": None,
        "bc_diff": None,
        "update_time": None
    }
    
    # 尝试从最新价格缓存获取
    latest_prices = db.query(LatestPrice).all()
    prices_map = {p.contract_code: p.price for p in latest_prices}
    
    cu_current = prices_map.get(cu_main)
    bc_current = prices_map.get(bc_main)
    
    if cu_current and bc_current:
        metrics = calculate_metrics(cu_current, bc_current)
        result["cu_current"] = cu_current
        result["bc_current"] = bc_current
        result["ratio"] = round(metrics["ratio"], 4)
        result["spread"] = round(metrics["spread"], 2)
        
        # 获取次月合约价格
        cu_next_price = prices_map.get(cu_next)
        bc_next_price = prices_map.get(bc_next)
        
        if cu_next_price and cu_current:
            result["cu_next"] = cu_next_price
            result["cu_diff"] = round(cu_current - cu_next_price, 2)
        
        if bc_next_price and bc_current:
            result["bc_next"] = bc_next_price
            result["bc_diff"] = round(bc_current - bc_next_price, 2)
        
        # 设置更新时间
        if latest_prices:
            result["update_time"] = max(p.update_time for p in latest_prices)
        
        return result
    
    return None


def get_history_data(db: Session, date_str: str) -> Optional[Dict]:
    """获取历史数据"""
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    cu_main, cu_next, bc_main, bc_next = get_current_contracts(day)
    
    result = {
        "date": date_str,
        "cu_main": None,
        "bc_main": None,
        "ratio": None,
        "spread": None,
        "cu_next": None,
        "bc_next": None,
        "cu_diff": None,
        "bc_diff": None
    }
    
    # 从价格记录表获取
    records = db.query(PriceRecord).filter(PriceRecord.date == date_str).all()
    
    if not records:
        return None
    
    prices_map = {r.contract_code: r.price for r in records}
    
    cu_main_price = prices_map.get(cu_main)
    bc_main_price = prices_map.get(bc_main)
    
    if cu_main_price and bc_main_price:
        metrics = calculate_metrics(cu_main_price, bc_main_price)
        result["cu_main"] = cu_main_price
        result["bc_main"] = bc_main_price
        result["ratio"] = round(metrics["ratio"], 4)
        result["spread"] = round(metrics["spread"], 2)
        
        cu_next_price = prices_map.get(cu_next)
        bc_next_price = prices_map.get(bc_next)
        
        if cu_next_price and cu_main_price:
            result["cu_next"] = cu_next_price
            result["cu_diff"] = round(cu_main_price - cu_next_price, 2)
        
        if bc_next_price and bc_main_price:
            result["bc_next"] = bc_next_price
            result["bc_diff"] = round(bc_main_price - bc_next_price, 2)
        
        return result
    
    return None