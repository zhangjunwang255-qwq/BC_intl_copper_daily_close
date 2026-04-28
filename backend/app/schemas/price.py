"""Pydantic Schemas"""
from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional


class PriceRecordBase(BaseModel):
    date: str
    contract_code: str
    price: float


class PriceRecordCreate(PriceRecordBase):
    pass


class PriceRecordResponse(PriceRecordBase):
    id: int
    update_time: datetime

    class Config:
        from_attributes = True


class LatestPriceResponse(BaseModel):
    contract_code: str
    price: float
    update_time: datetime

    class Config:
        from_attributes = True


class LatestDataResponse(BaseModel):
    """当前最新数据响应"""
    date: str
    cu_current: float
    bc_current: float
    ratio: float
    spread: float
    cu_next: Optional[float] = None
    bc_next: Optional[float] = None
    cu_diff: Optional[float] = None
    bc_diff: Optional[float] = None
    update_time: datetime


class HistoryDataResponse(BaseModel):
    """历史数据响应"""
    date: str
    cu_main: float
    bc_main: float
    ratio: float
    spread: float
    cu_next: Optional[float] = None
    bc_next: Optional[float] = None
    cu_diff: Optional[float] = None
    bc_diff: Optional[float] = None


class BackfillResponse(BaseModel):
    """回填任务响应"""
    status: str
    message: str
    records_filled: int = 0