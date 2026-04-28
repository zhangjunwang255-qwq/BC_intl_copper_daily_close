"""最新数据 API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import date

from app.db.database import get_db
from app.schemas.price import LatestDataResponse
from app.services.price_service import get_current_contracts, calculate_metrics
from app.models.price import LatestPrice

router = APIRouter()


@router.get("/latest", response_model=LatestDataResponse)
async def get_latest(db: Session = Depends(get_db)):
    """获取当前日期对应的所有必需价格及计算指标"""
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
    
    # 从最新价格缓存获取
    latest_prices = db.query(LatestPrice).all()
    if not latest_prices:
        return result
    
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
        result["update_time"] = max(p.update_time for p in latest_prices)
    
    return result