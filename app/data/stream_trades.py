from alpaca.data.live import StockDataStream
from aggregator import CandleAggregator
from config import *
import asyncio, json

redis_client = redis.Redis(host="redis", port=6379, decode_responses=True)


# Initialize the in-memory candle aggregator (1-minute candles)
aggregator = CandleAggregator(interval=60)

# Initialize the StockDataStream
stock_stream = StockDataStream(ALPACA_KEY, ALPACA_SECRET)

# Define the trade handler
async def handle_trade(trade):
    await aggregator.add_trade(trade)
    
    print(f"[TRADE] {trade.symbol} {trade.price} x {trade.size} at {trade.timestamp}")

async def flush_loop():
    while True:
        await asyncio.sleep(60)  # check every 5 seconds
        bars = aggregator.pop_ready_bars()
        for bar in bars:
            await redis_client.rpush("candles", json.dumps(bar))
            print(f"Pushed candle to Redis: {bar['symbol']} @ {bar['datetime']}")

# Subscribe to trade updates for specific symbols
stock_stream.subscribe_trades(handle_trade, "QQQ", "SPY")

# Run the stream
def start_stream():
    loop = asyncio.get_event_loop()
    loop.create_task(flush_loop())
    stock_stream.run()

# Optionally call this from main.py or a background task
if __name__ == "__main__":
    start_stream()