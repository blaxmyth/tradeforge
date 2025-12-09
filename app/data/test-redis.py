import redis, json
r = redis.Redis(host="redis", port=6379, decode_responses=True)
bar = {"symbol": "AAPL", "datetime": "2024-04-04T15:00:00", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 15000}
r.rpush("candles", json.dumps(bar))