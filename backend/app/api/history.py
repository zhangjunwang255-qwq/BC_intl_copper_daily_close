"""历史数据 API"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from app.db.database import get_db
from app.schemas.price import HistoryDataResponse
from app.services.price_service import get_current_contracts, calculate_metrics
from app.models.price import PriceRecord

router = APIRouter()


@router.get("/history", response_model=HistoryDataResponse)
async def get_history(
    date: str = Query(..., description="日期，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    """获取指定日期的历史快照数据"""
    # 验证日期格式
    try:
        query_date = date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式")
    
    cu_main, cu_next, bc_main, bc_next = get_current_contracts(query_date)
    
    result = {
        "date": date,
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
    records = db.query(PriceRecord).filter(PriceRecord.date == date).all()
    
    if not records:
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的历史数据")
    
    prices_map = {r.contract_code: r.price for r in records}
    
    cu_main_price = prices_map.get(cu_main)
    bc_main_price = prices_map.get(bc_main)
    
    if not cu_main_price or not bc_main_price:
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的完整数据")
    
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