from datetime import datetime, timedelta
from collections import defaultdict
import pytz

class CandleAggregator:
    def __init__(self, interval=timedelta(minutes=1)):
        self.interval = interval
        self.current_candles = {}  # symbol → (start_time, bar)
        self.bars_to_save = []

    def _round_time(self, dt):
        return dt.replace(second=0, microsecond=0)

    async def add_trade(self, trade):
        symbol = trade.symbol
        price = trade.price
        volume = trade.size
        ts = trade.timestamp.replace(tzinfo=pytz.UTC)
        bucket = self._round_time(ts)

        candle = self.current_candles.get(symbol)

        if candle and candle[0] != bucket:
            # Emit previous bar
            self.bars_to_save.append(candle[1])
            self.current_candles.pop(symbol)

        # if candle and (ts - candle[0]) > timedelta(seconds=10):
        #     self.bars_to_save.append(candle[1])
        #     self.current_candles.pop(symbol)


        if symbol not in self.current_candles:
            self.current_candles[symbol] = (bucket, {
                "symbol": symbol,
                "datetime": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            })
            print(f"[DEBUG] Added trade to {symbol}: {price} x {volume} at {bucket}")
        else:
            bar = self.current_candles[symbol][1]
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
            bar["volume"] += volume

    def pop_ready_bars(self):
        now = datetime.utcnow().replace(second=0, microsecond=0, tzinfo=pytz.UTC)
        expired_symbols = []

        for symbol, (start_time, bar) in self.current_candles.items():
            if now > start_time + self.interval:
                self.bars_to_save.append(bar)
                expired_symbols.append(symbol)

        for symbol in expired_symbols:
            self.current_candles.pop(symbol)

        bars = self.bars_to_save[:]
        self.bars_to_save = []
        return bars
