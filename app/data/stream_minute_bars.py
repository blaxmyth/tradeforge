# stream.py

from alpaca.data.live import StockDataStream
from config import *
from db.models import Asset, AssetPrice, WatchList
from db.database import *
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import pytz

stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET)

# watchlist = session.execute(
#     select(WatchList).options(selectinload(WatchList.asset))
# )
# watchlist = watchlist.scalars().all()

# symbols = [entry.asset.symbol for entry in watchlist if entry.asset]
    
async def on_minute_bar(bar):
    async with async_session_maker() as session:
        result = await session.execute(select(Asset))
        asset_map = {a.symbol: a.id for a in result.scalars()}
        
        asset_id = asset_map.get(bar.symbol)
        if not asset_id:
            print(f"Symbol not found: {bar.symbol}")
            return
        
        bar.timestamp = bar.timestamp.astimezone(pytz.timezone("US/Eastern")).replace(tzinfo=None)

        candle = AssetPrice(
            asset_id=asset_id,
            datetime=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume
        )

        session.add(candle)
        await session.commit()
        print(f"Inserted bar for {bar.symbol} @ {bar.timestamp}")


stream.subscribe_bars(on_minute_bar, "QQQ", "SPY")
stream.run()
# try:
#     stream.run()
# except Exception as e:
#     print("The market is closed")

# # stream.py

# import asyncio
# import pytz
# from alpaca.data.live import StockDataStream
# from config import *
# from db.models import Asset, AssetPrice, WatchList
# from db.database import async_session_maker
# from sqlalchemy.future import select
# from sqlalchemy.orm import selectinload

# stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET, paper=True)
# watchlist_symbols = set()

# async def get_watchlist_symbols():
#     async with async_session_maker() as session:
#         result = await session.execute(
#             select(WatchList).options(selectinload(WatchList.asset))
#         )
#         watchlist = result.scalars().all()
#         return {entry.asset.symbol for entry in watchlist if entry.asset}

# async def on_minute_bar(bar):
#     if bar.symbol not in watchlist_symbols:
#         print(f"⏭ Skipping {bar.symbol} (not in watchlist)")
#         return

#     async with async_session_maker() as session:
#         result = await session.execute(select(Asset))
#         asset_map = {a.symbol: a.id for a in result.scalars()}
#         asset_id = asset_map.get(bar.symbol)
#         if not asset_id:
#             print(f"❌ Asset not found for: {bar.symbol}")
#             return

#         ts = bar.timestamp.astimezone(pytz.timezone("US/Eastern")).replace(tzinfo=None)
#         candle = AssetPrice(
#             asset_id=asset_id,
#             datetime=ts,
#             open=bar.open,
#             high=bar.high,
#             low=bar.low,
#             close=bar.close,
#             volume=bar.volume
#         )

#         session.add(candle)
#         await session.commit()
#         print(f"✅ Saved bar for {bar.symbol} @ {ts}")

# async def start_stream():
#     global watchlist_symbols
#     watchlist_symbols = await get_watchlist_symbols()

#     if not watchlist_symbols:
#         print("❗ No symbols in watchlist.")
#         return

#     print(f"✅ Subscribing to: {watchlist_symbols}")
#     stream.subscribe_bars(on_minute_bar, *watchlist_symbols)
#     stream.run()  # ✅ blocking call, DO NOT await

# if __name__ == "__main__":
#     try:
#         asyncio.run(start_stream())  # ✅ Perfectly fine inside Docker
#     except KeyboardInterrupt:
#         print("🛑 Stream manually stopped.")

