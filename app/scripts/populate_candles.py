# tasks/save_candles.py

from app.db.database import async_session_maker
from app.db.models import AssetPrice, Asset
from app.celery_app import celery
from sqlalchemy.ext.asyncio import AsyncSession
import redis
import json
import asyncio

redis = redis.Redis(host="redis", port=6379, decode_responses=True)

async def _save():
    async with async_session_maker() as session:  # type: AsyncSession
        # Pull all staged candles from Redis
        bars = []
        while True:
            raw = redis.lpop("candles")
            if not raw:
                break
            bars.append(json.loads(raw))

        if not bars:
            print("No candles in Redis.")
            return

        # Build asset_id map
        result = await session.execute(select(Asset))
        asset_map = {a.symbol: a.id for a in result.scalars()}

        # Save to DB
        to_insert = []
        for bar in bars:
            asset_id = asset_map.get(bar["symbol"])
            if not asset_id:
                continue
            to_insert.append(AssetPrice(
                asset_id=asset_id,
                datetime=bar["datetime"],
                open=bar["open"],
                high=bar["high"],
                low=bar["low"],
                close=bar["close"],
                volume=bar["volume"],
            ))

        session.add_all(to_insert)
        await session.commit()
        print(f"✅ Inserted {len(to_insert)} candles to DB")
