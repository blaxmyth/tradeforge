from celery import Celery
from celery.schedules import crontab
from scripts.populate_assets import populate_assets
from strats.opening_range_strategy import opening_range_strategy
from db.models import *
from db.database import *
from sqlalchemy import text
import asyncio

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
    # Runs every minute 9 AM–4 PM ET weekdays; script itself enforces 9:45 minimum
    "run-opening-range-strategy": {
        "task": "tasks.tasks.run_opening_range_strategy",
        "schedule": crontab(minute="*/1", hour="9-15", day_of_week="1-5"),
    },
    # Refresh continuous aggregates every 5 min during market hours
    # (TimescaleDB BGW is unreliable in Docker)
    "refresh-continuous-aggregates": {
        "task": "tasks.tasks.refresh_continuous_aggregates",
        "schedule": crontab(minute="*/5", hour="9-16", day_of_week="1-5"),
    },
}

@celery.task
def run_populate_assets():
    loop = asyncio.get_event_loop()

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(_run())

async def _run():
    async with AsyncSessionMaker() as session:
        await populate_assets(session)


@celery.task
def run_opening_range_strategy():
    opening_range_strategy()


_CONTINUOUS_AGGREGATES = [
    "asset_price_5min",
    "asset_price_15min",
    "asset_price_1hr",
    "asset_price_1day",
]

@celery.task
def refresh_continuous_aggregates():
    # Must run outside a transaction block — use AUTOCOMMIT
    with sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for view in _CONTINUOUS_AGGREGATES:
            conn.execute(text(
                f"CALL refresh_continuous_aggregate('{view}', "
                f"(NOW() - INTERVAL '2 days')::timestamp, NOW()::timestamp)"
            ))