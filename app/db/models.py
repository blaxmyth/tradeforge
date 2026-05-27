from sqlalchemy import Column, Integer, Float, String, Boolean, ForeignKey, Date, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Asset(Base):
    __tablename__ = "asset"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False)
    name = Column(String)
    exchange = Column(String)
    asset_class = Column(String)
    is_etf = Column(Boolean)
    is_sp500 = Column(Boolean)

class AssetPrice(Base):
    __tablename__ = "asset_price"

    datetime = Column(DateTime, nullable=False, primary_key=True)
    asset_id = Column(ForeignKey("asset.id"), nullable=False, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)

    __table_args__ = (
        Index("ix_asset_id", "asset_id", "datetime"),
    )

class Indicator(Base):
    __tablename__ = "indicator"

    datetime = Column(DateTime, nullable=False, primary_key=True)
    asset_id = Column(ForeignKey("asset.id"), nullable=False, primary_key=True)
    rsi = Column(Float)
    macd = Column(Float)
    macdh = Column(Float)
    macds = Column(Float)
    adx = Column(Float)
    adx_dmp = Column(Float)
    adx_dmn = Column(Float)
    sma_200 = Column(Float)

class Strategy(Base):
    __tablename__ = "strategy"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

class AssetStrategy(Base):
    __tablename__ = "asset_strategy"

    asset_id = Column(ForeignKey("asset.id"), nullable=False, primary_key=True)
    strategy_id = Column(ForeignKey("strategy.id"), nullable=False)
    assets = relationship("Asset", foreign_keys=[asset_id], uselist=True)

class User(Base):
    __tablename__ = "user"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    email = Column(String, nullable=False)
    password = Column(String, nullable=False)
    phone = Column(String, nullable=False)

class WatchList(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    asset_id = Column(ForeignKey("asset.id"), nullable=False)
    user_id = Column(ForeignKey("user.id"), nullable=False)

    asset = relationship("Asset")

    __table_args__ = (
        UniqueConstraint("user_id", "asset_id"),
    )

class ETFHolding(Base):
    __tablename__ = "etf_holding"

    etf_id = Column(ForeignKey("asset.id"), nullable=False, primary_key=True)
    holding_id = Column(ForeignKey("asset.id"), nullable=False, primary_key=True)
    dt =  Column(Date, primary_key=True)
    shares = Column(Integer)
    weight = Column(Integer)
    name = Column(String, nullable=False)