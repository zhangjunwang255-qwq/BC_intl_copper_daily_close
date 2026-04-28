"""SQLAlchemy 模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from app.db.database import Base


class PriceRecord(Base):
    """价格记录模型"""
    __tablename__ = "price_records"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    contract_code = Column(String(20), nullable=False)    # CU2606, BC2606 等
    price = Column(Float, nullable=False)
    update_time = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_date_contract', 'date', 'contract_code', unique=True),
    )


class LatestPrice(Base):
    """最新价格缓存表"""
    __tablename__ = "latest_prices"
    
    id = Column(Integer, primary_key=True, index=True)
    contract_code = Column(String(20), nullable=False, unique=True)
    price = Column(Float, nullable=False)
    update_time = Column(DateTime, default=datetime.utcnow)