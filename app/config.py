import os
import redis.asyncio as redis

POLYGON_URL = os.getenv("POLYGON_URL")
POLYGON_KEY = os.getenv("POLYGON_KEY")

ALPACA_URL = os.getenv("ALPACA_URL")
ALPACA_KEY = os.getenv("ALPACA_KEY")
ALPACA_SECRET = os.getenv("ALPACA_SECRET")

ALPACA_BROKER_KEY = os.getenv("ALPACA_BROKER_KEY")
ALPACA_BROKER_SECRET = os.getenv("ALPACA_BROKER_SECRET")
ALPACA_BROKER_URL = os.getenv("ALPACA_BROKER_URL")

TRADIER_URL = os.getenv("TRADIER_URL")
TRADIER_SANDBOX_URL = os.getenv("TRADIER_SANDBOX_UR")
TRADIER_SANDBOX_KEY = os.getenv("TRADIER_SANDBOX_KEY")

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

ACCESS_TOKEN_EXPIRE_MINUTES = 30
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
