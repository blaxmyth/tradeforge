from fastapi import Depends
from datetime import datetime
from celery import Celery
from celery.schedules import crontab
from scripts.populate_assets import populate_assets
from db.models import *
from db.database import *
import asyncio, json
from data import aggregator
from sqlalchemy.future import select

redis = redis.Redis(host="redis", port=6379, decode_responses=True)

celery = Celery(
    "worker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/0",
)

celery.conf.timezone = "US/Eastern"

celery.conf.beat_schedule = {
    "run-populate-assets": {
        "task": "tasks.tasks.run_populate_assets",
        "schedule": crontab(minute=0, hour=23, day_of_week='1-5'),  
    },
    "run-populate-candles": {
        "task": "tasks.tasks.run_populate_candles",
        "schedule": crontab(minute="*/5")
    }
}

@celery.task
def run_populate_assets():
    loop = asyncio.get_event_loop()

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(_run())

async def _run():
    async with async_session_maker() as session:
        await populate_assets(session)

@celery.task
def run_populate_candles():
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # No event loop in current thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(_save())

async def _save():
    async with async_session_maker() as session:  # type: AsyncSession
        # Pull all staged candles from Redis
        bars = []
        while True:
            raw = await redis.lpop("candles")
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
            bar["datetime"] = datetime.fromisoformat(bar["datetime"])
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
        print(f"Inserted {len(to_insert)} candles to DB")