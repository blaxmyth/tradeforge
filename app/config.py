import os
import redis.asyncio as redis

POLYGON_URL = os.getenv("POLYGON_URL", "https://api.polygon.io/v3/")
POLYGON_KEY = os.getenv("POLYGON_KEY")

ALPACA_URL = os.getenv("ALPACA_URL", "https://paper-api.alpaca.markets/v2")
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")

ALPACA_BROKER_KEY = os.getenv("ALPACA_BROKER_KEY")
ALPACA_BROKER_SECRET = os.getenv("ALPACA_BROKER_SECRET")
ALPACA_BROKER_URL = os.getenv("ALPACA_BROKER_URL", "https://broker-api.sandbox.alpaca.markets")

TRADIER_URL = os.getenv("TRADIER_URL", "https://api.tradier.com/v1/")
TRADIER_SANDBOX_URL = os.getenv("TRADIER_SANDBOX_URL", "https://sandbox.tradier.com/v1/")
TRADIER_SANDBOX_KEY = os.getenv("TRADIER_SANDBOX_KEY")

DB_HOST = os.getenv("DB_HOST", "timescale-db")
DB_USER = os.getenv("DB_USER", "timescale")
DB_PASS = os.getenv("DB_PASS", "timescale")
DB_NAME = os.getenv("DB_NAME", "tradeforge")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

ACCESS_TOKEN_EXPIRE_MINUTES = 30
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
