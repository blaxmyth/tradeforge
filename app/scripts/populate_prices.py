import pandas as pd
from datetime import datetime
from config import *
from alpaca.data import CryptoHistoricalDataClient, OptionHistoricalDataClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest, OptionBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from sqlalchemy.ext.asyncio import AsyncSession
from dateutil.relativedelta import relativedelta
from sqlalchemy.future import select
from db.models import *
from db.database import *
import asyncio
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

async def fetch_bars(client, request_params):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        bars = await loop.run_in_executor(pool, client.get_stock_bars, request_params)
    return bars

async def populate_prices(db: AsyncSession):

    client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

    query = select(Asset)
    result = await db.scalars(query)
    existing_assets = result.all()

    stock_symbols = []

    for existing_asset in existing_assets:
        if existing_asset.asset_class == "us_equity":
            stock_symbols.append(existing_asset.symbol)

    asset_dict = {}

    for asset in existing_assets:
        asset_dict[asset.symbol] = asset.id

    batch_size = 100

    for i in range(0, len(existing_assets), batch_size):
        symbol_batch = stock_symbols[i:i+batch_size]

        request_params = StockBarsRequest(
                            symbol_or_symbols=symbol_batch,
                            timeframe=TimeFrame.Hour,
                            start=datetime.now() - relativedelta(days=7),
                            end=datetime.today()
                        )
        
        bars = await fetch_bars(client, request_params)
        bars = bars.df

        to_insert = []

        for row in bars.itertuples():
            symbol, timestamp = row.Index

            timestamp = timestamp.astimezone(ZoneInfo("America/New_York"))

            timestamp = timestamp.replace(tzinfo=None)

            print(f"Inserting bar for {symbol} at {timestamp}")

            bar = AssetPrice(
                asset_id=asset_dict[symbol],
                datetime=timestamp,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
            )
            to_insert.append(bar)

        db.add_all(to_insert)
        await db.commit()