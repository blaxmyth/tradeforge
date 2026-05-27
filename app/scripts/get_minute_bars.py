import asyncio
from alpaca.data.live import StockDataStream
from config import * # Assuming ALPACA_KEY and ALPACA_SECRET are defined here
from db.models import Asset, AssetPrice, WatchList
from db.database import async_session_maker # Assuming this is your async session maker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import pytz

# Initialize the stream client
stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET)


async def get_watchlist_symbols():
    """
    Asynchronously queries the database to get all stock symbols 
    currently listed in the WatchList.
    """
    async with async_session_maker() as session:
        # Fetch WatchList entries, eagerly loading the associated Asset
        result = await session.execute(
            select(WatchList).options(selectinload(WatchList.asset))
        )
        watchlist_entries = result.scalars().all()
        
        # Extract symbols, ensuring the asset relationship loaded correctly
        symbols = [entry.asset.symbol for entry in watchlist_entries if entry.asset]
        
        print(f"Subscribing to {len(symbols)} symbols from WatchList: {symbols}")
        return symbols


async def on_minute_bar(bar):
    """
    Callback function executed every time a new minute bar is received.
    """
    async with async_session_maker() as session:
        # Fetch the mapping of symbols to asset IDs once per connection is more efficient,
        # but fetching inside the session block ensures it's up-to-date and session-bound.
        result = await session.execute(select(Asset))
        asset_map = {a.symbol: a.id for a in result.scalars()}
        
        asset_id = asset_map.get(bar.symbol)
        if not asset_id:
            print(f"Symbol not found: {bar.symbol}")
            return
        
        # Convert the Alpaca timestamp to US/Eastern timezone and remove tzinfo for DB insertion
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


# --- Main Execution Logic ---

# 1. Synchronously run the async function to fetch the necessary symbols list
# This must happen before we start the blocking stream.run() call.
try:
    symbols_to_subscribe = asyncio.run(get_watchlist_symbols())
except Exception as e:
    print(f"Failed to fetch symbols from database: {e}")
    # Handle error, potentially exit or use a fallback list
    symbols_to_subscribe = ["SPY", "QQQ"] # Fallback
    print(f"Using fallback symbols: {symbols_to_subscribe}")


if symbols_to_subscribe:
    # 2. Subscribe to the fetched list of symbols using the unpacking operator (*)
    # Note: Alpaca requires BAR data subscriptions to be uppercase symbols.
    stream.subscribe_bars(on_minute_bar, *(s.upper() for s in symbols_to_subscribe))
    
    # 3. Start the stream
    stream.run()
else:
    print("WatchList is empty. Not starting the data stream.")